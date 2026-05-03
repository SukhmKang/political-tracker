from fastapi import APIRouter, HTTPException, Query

from db import db
from models import (
    BulkMergeRequest, BulkMergeResponse,
    MergeCandidateEntity, MergeCandidateGroup, MergeCandidatesResponse,
    MergeRequest, MergeResponse,
)

router = APIRouter()


@router.get("/entities/merge-candidates", response_model=MergeCandidatesResponse)
async def get_merge_candidates(
    sample_size: int = Query(default=10, ge=1, le=50),
):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute(
            """
            WITH duplicate_groups AS (
                SELECT normalized_name, state,
                       COUNT(*) - 1 AS would_delete,
                       SUM(COALESCE(mention_count, 0)) AS total_mentions
                FROM unified.entities
                GROUP BY normalized_name, state
                HAVING COUNT(*) > 1
            )
            SELECT SUM(would_delete)::int, COUNT(*)::int FROM duplicate_groups
            """
        )
        totals = await cur.fetchone()

    total_would_delete = int(totals[0] or 0)
    total_groups = int(totals[1] or 0)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            WITH duplicate_groups AS (
                SELECT normalized_name, state,
                       SUM(COALESCE(mention_count, 0)) AS total_mentions
                FROM unified.entities
                GROUP BY normalized_name, state
                HAVING COUNT(*) > 1
                ORDER BY SUM(COALESCE(mention_count, 0)) DESC
                LIMIT %s
            )
            SELECT e.id, e.canonical_name, e.normalized_name, e.state,
                   e.entity_type, COALESCE(e.mention_count, 0), r.name
            FROM unified.entities e
            JOIN duplicate_groups dg
              ON e.normalized_name = dg.normalized_name
             AND (e.state = dg.state OR (e.state IS NULL AND dg.state IS NULL))
            LEFT JOIN unified.entity_resolution_runs r ON r.id = e.run_id
            ORDER BY e.normalized_name, e.state, COALESCE(e.mention_count, 0) DESC
            """,
            (sample_size,),
        )
        rows = await cur.fetchall()

    groups: dict[tuple, list] = {}
    for row in rows:
        entity_id, canonical_name, normalized_name, state, entity_type, mention_count, run_name = row
        key = (normalized_name, state)
        if key not in groups:
            groups[key] = []
        groups[key].append(MergeCandidateEntity(
            id=entity_id, canonical_name=canonical_name, entity_type=entity_type,
            mention_count=mention_count, run_name=run_name,
        ))

    sample_groups = []
    for (normalized_name, state), entities in groups.items():
        sorted_entities = sorted(entities, key=lambda e: e.mention_count, reverse=True)
        sample_groups.append(MergeCandidateGroup(
            normalized_name=normalized_name,
            state=state,
            entity_count=len(entities),
            keep_id=sorted_entities[0].id,
            discard_ids=[e.id for e in sorted_entities[1:]],
            total_mentions=sum(e.mention_count for e in entities),
            entities=sorted_entities,
        ))

    sample_groups.sort(key=lambda g: g.total_mentions, reverse=True)

    return MergeCandidatesResponse(
        total_groups=total_groups,
        total_would_delete=total_would_delete,
        sample_groups=sample_groups,
    )


@router.post("/entities/merge-bulk", response_model=BulkMergeResponse)
async def merge_entities_bulk(req: BulkMergeRequest):
    if not req.merges:
        raise HTTPException(status_code=400, detail="merges list is empty")

    all_keep_ids = {m.keep_id for m in req.merges}
    all_discard_ids = [d for m in req.merges for d in m.discard_ids]
    conflicts = all_keep_ids & set(all_discard_ids)
    if conflicts:
        raise HTTPException(status_code=400, detail=f"IDs appear as both keep and discard: {sorted(conflicts)}")

    pairs = [(discard_id, m.keep_id) for m in req.merges for discard_id in m.discard_ids]
    conn = await db()

    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                "CREATE TEMP TABLE _merge_map (discard_id bigint NOT NULL, keep_id bigint NOT NULL) ON COMMIT DROP"
            )
            await cur.executemany("INSERT INTO _merge_map VALUES (%s, %s)", pairs)
            await cur.execute("CREATE INDEX ON _merge_map (discard_id)")

        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE unified.entities e
                SET mention_count = e.mention_count + agg.extra
                FROM (
                    SELECT keep_id, SUM(COALESCE(d.mention_count, 0)) AS extra
                    FROM _merge_map mm JOIN unified.entities d ON d.id = mm.discard_id
                    GROUP BY keep_id
                ) agg
                WHERE e.id = agg.keep_id
                """
            )

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.official_edges SET source_entity_id = mm.keep_id FROM _merge_map mm WHERE source_entity_id = mm.discard_id"
            )
            src_remapped = cur.rowcount
            await cur.execute(
                "UPDATE unified.official_edges SET target_entity_id = mm.keep_id FROM _merge_map mm WHERE target_entity_id = mm.discard_id"
            )
            tgt_remapped = cur.rowcount
        official_edges_remapped = src_remapped + tgt_remapped

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM unified.official_edges WHERE source_entity_id = target_entity_id")
            self_edges_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM unified.official_edges
                WHERE source_row_id IS NOT NULL
                  AND id NOT IN (
                      SELECT MIN(id) FROM unified.official_edges
                      WHERE source_row_id IS NOT NULL
                      GROUP BY source_entity_id, target_entity_id, source_table, source_row_id
                  )
                """
            )
            duplicate_edges_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.inferred_edges SET seed_entity_id = mm.keep_id FROM _merge_map mm WHERE seed_entity_id = mm.discard_id"
            )
            ie_src = cur.rowcount
            await cur.execute(
                "UPDATE unified.inferred_edges SET target_entity_id = mm.keep_id FROM _merge_map mm WHERE target_entity_id = mm.discard_id"
            )
            ie_tgt = cur.rowcount
            await cur.execute("DELETE FROM unified.inferred_edges WHERE seed_entity_id = target_entity_id")
            await cur.execute(
                """
                DELETE FROM unified.inferred_edges
                WHERE id NOT IN (
                    SELECT MIN(id) FROM unified.inferred_edges
                    GROUP BY seed_entity_id, target_entity_id, relationship_type
                )
                """
            )
        inferred_edges_remapped = ie_src + ie_tgt

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.entity_mentions SET entity_id = mm.keep_id FROM _merge_map mm WHERE entity_id = mm.discard_id"
            )
            mentions_remapped = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM unified.entity_enrichments WHERE entity_id IN (SELECT discard_id FROM _merge_map)")
            enrichments_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM unified.entities WHERE id IN (SELECT discard_id FROM _merge_map)")
            entities_deleted = cur.rowcount

    return BulkMergeResponse(
        groups_processed=len(req.merges),
        entities_deleted=entities_deleted,
        official_edges_remapped=official_edges_remapped,
        self_edges_deleted=self_edges_deleted,
        duplicate_edges_deleted=duplicate_edges_deleted,
        inferred_edges_remapped=inferred_edges_remapped,
        mentions_remapped=mentions_remapped,
        enrichments_deleted=enrichments_deleted,
    )


@router.post("/entities/merge", response_model=MergeResponse)
async def merge_entities(req: MergeRequest):
    if req.keep_id in req.discard_ids:
        raise HTTPException(status_code=400, detail="keep_id must not appear in discard_ids")
    if not req.discard_ids:
        raise HTTPException(status_code=400, detail="discard_ids must not be empty")

    all_ids = [req.keep_id] + req.discard_ids
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM unified.entities WHERE id = ANY(%s::int[])", (all_ids,))
        found = {row[0] for row in await cur.fetchall()}

    missing = set(all_ids) - found
    if missing:
        raise HTTPException(status_code=404, detail=f"Entity IDs not found: {sorted(missing)}")

    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.official_edges SET source_entity_id = %s WHERE source_entity_id = ANY(%s::int[])",
                (req.keep_id, req.discard_ids),
            )
            src_remapped = cur.rowcount
            await cur.execute(
                "UPDATE unified.official_edges SET target_entity_id = %s WHERE target_entity_id = ANY(%s::int[])",
                (req.keep_id, req.discard_ids),
            )
            tgt_remapped = cur.rowcount
        edges_remapped = src_remapped + tgt_remapped

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM unified.official_edges WHERE source_entity_id = target_entity_id")
            self_edges_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM unified.official_edges
                WHERE source_row_id IS NOT NULL
                  AND id NOT IN (
                      SELECT MIN(id) FROM unified.official_edges WHERE source_row_id IS NOT NULL
                      GROUP BY source_entity_id, target_entity_id, source_table, source_row_id
                  )
                  AND (source_entity_id = %s OR target_entity_id = %s)
                """,
                (req.keep_id, req.keep_id),
            )
            duplicate_edges_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.inferred_edges SET seed_entity_id = %s WHERE seed_entity_id = ANY(%s::int[])",
                (req.keep_id, req.discard_ids),
            )
            await cur.execute(
                "UPDATE unified.inferred_edges SET target_entity_id = %s WHERE target_entity_id = ANY(%s::int[])",
                (req.keep_id, req.discard_ids),
            )
            await cur.execute("DELETE FROM unified.inferred_edges WHERE seed_entity_id = target_entity_id")
            await cur.execute(
                """
                DELETE FROM unified.inferred_edges
                WHERE id NOT IN (
                    SELECT MIN(id) FROM unified.inferred_edges
                    GROUP BY seed_entity_id, target_entity_id, relationship_type
                )
                AND (seed_entity_id = %s OR target_entity_id = %s)
                """,
                (req.keep_id, req.keep_id),
            )

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE unified.entity_mentions SET entity_id = %s WHERE entity_id = ANY(%s::int[])",
                (req.keep_id, req.discard_ids),
            )
            mentions_remapped = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM unified.entity_enrichments WHERE entity_id = ANY(%s::int[])",
                (req.discard_ids,),
            )
            enrichments_deleted = cur.rowcount

        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE unified.entities
                SET mention_count = (
                    SELECT COALESCE(SUM(mention_count), 0)
                    FROM unified.entities WHERE id = ANY(%s::int[])
                )
                WHERE id = %s
                """,
                (all_ids, req.keep_id),
            )

        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM unified.entities WHERE id = ANY(%s::int[])", (req.discard_ids,))

    return MergeResponse(
        kept_id=req.keep_id,
        discarded_ids=req.discard_ids,
        edges_remapped=edges_remapped,
        self_edges_deleted=self_edges_deleted,
        duplicate_edges_deleted=duplicate_edges_deleted,
        mentions_remapped=mentions_remapped,
        enrichments_deleted=enrichments_deleted,
    )
