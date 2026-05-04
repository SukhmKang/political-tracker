from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from db import db, get_agent_inferred_run_id
from models import (
    EntityInfo, EntityProfile, EntitySearchResult,
    Finance, GraphEdge, GraphNode, InferredEdge, InferredEdgesResponse,
    Neighborhood, RecentEdge,
)

router = APIRouter()

_INFERRED_SELECT = """
    SELECT id, seed_entity_id, seed_entity_name,
           target_name, target_entity_id, target_type, relationship_type,
           COALESCE(evidence_quotes, '{}'),
           COALESCE(source_urls, '{}'),
           COALESCE(source_domains, '{}'),
           evidence_strength,
           COALESCE(found_by, '{}'),
           COALESCE(depth, 1),
           found_from,
           verified,
           created_at
    FROM unified.inferred_edges
"""

_INFERRED_ORDER = """
    ORDER BY
        CASE evidence_strength
            WHEN 'direct'   THEN 1
            WHEN 'indirect' THEN 2
            WHEN 'weak'     THEN 3
            ELSE 4
        END,
        created_at DESC
"""


def _build_inferred_edge(r: tuple) -> InferredEdge:
    return InferredEdge(
        id=r[0],
        seed_entity_id=r[1],
        seed_entity_name=r[2],
        target_name=r[3],
        target_entity_id=r[4],
        target_type=r[5],
        relationship_type=r[6],
        evidence_quotes=list(r[7] or []),
        source_urls=list(r[8] or []),
        source_domains=list(r[9] or []),
        evidence_strength=r[10],
        found_by=list(r[11] or []),
        depth=int(r[12] or 1),
        found_from=r[13],
        verified=r[14],
        created_at=r[15].isoformat() if r[15] else "",
    )


@router.get("/entities/search", response_model=list[EntitySearchResult])
async def search_entities(
    q: str = Query(..., min_length=2, max_length=200),
    entity_type: Optional[str] = None,
    state_code: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    conn = await db()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, canonical_name, entity_type, state, city, state_code, zip5,
                   COALESCE(mention_count, 0),
                   word_similarity(lower(%s), normalized_name) AS score
            FROM unified.entities
            WHERE normalized_name ILIKE '%%' || lower(%s) || '%%'
              AND mention_count > 5
              AND (%s::text IS NULL OR entity_type = %s)
              AND (%s::text IS NULL OR state_code = upper(%s))
            ORDER BY score DESC, mention_count DESC
            LIMIT %s
            """,
            (q, q, entity_type, entity_type, state_code, state_code, limit),
        )
        rows = await cur.fetchall()

    return [
        EntitySearchResult(
            id=r[0], name=r[1], type=r[2], state=r[3], city=r[4],
            state_code=r[5], zip5=r[6], mention_count=r[7], score=float(r[8]),
        )
        for r in rows
    ]


@router.get("/entities/{entity_id}/neighborhood", response_model=Neighborhood)
async def get_neighborhood(
    entity_id: int,
    hops: int = Query(default=1, ge=1, le=2),
    max_nodes: int = Query(default=100, ge=1, le=500),
    max_edges: int = Query(default=500, ge=1, le=2000),
    include_inferred: bool = Query(default=False),
    direction: Optional[Literal["incoming", "outgoing"]] = Query(default=None),
):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM unified.entities WHERE id = %s", (entity_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    depth_map: dict[int, int] = {entity_id: 0}

    if direction and hops == 1:
        counterparty_expr = "source_entity_id" if direction == "incoming" else "target_entity_id"
        filter_column = "target_entity_id" if direction == "incoming" else "source_entity_id"
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {counterparty_expr} AS neighbor_id
                FROM unified.official_edges
                WHERE {filter_column} = %s
                GROUP BY {counterparty_expr}
                ORDER BY SUM(COALESCE(amount, 0)) DESC NULLS LAST
                LIMIT %s
                """,
                (entity_id, max(max_nodes - 1, 0)),
            )
            rows = await cur.fetchall()
        for (neighbor_id,) in rows:
            depth_map[neighbor_id] = 1
    else:
        frontier: list[int] = [entity_id]
        for hop in range(1, hops + 1):
            if not frontier or len(depth_map) >= max_nodes:
                break
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT DISTINCT
                        CASE WHEN source_entity_id = ANY(%s::int[])
                             THEN target_entity_id
                             ELSE source_entity_id END AS neighbor_id
                    FROM unified.official_edges
                    WHERE source_entity_id = ANY(%s::int[])
                       OR target_entity_id = ANY(%s::int[])
                    """,
                    (frontier, frontier, frontier),
                )
                rows = await cur.fetchall()
            new_frontier: list[int] = []
            for (neighbor_id,) in rows:
                if neighbor_id not in depth_map:
                    depth_map[neighbor_id] = hop
                    new_frontier.append(neighbor_id)
                    if len(depth_map) >= max_nodes:
                        break
            frontier = new_frontier

    all_node_ids = list(depth_map.keys())

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, canonical_name, entity_type, state, COALESCE(mention_count, 0)
            FROM unified.entities
            WHERE id = ANY(%s::int[])
            """,
            (all_node_ids,),
        )
        entity_rows = await cur.fetchall()

    nodes = [
        GraphNode(id=r[0], name=r[1], type=r[2], state=r[3], mention_count=r[4], depth=depth_map[r[0]])
        for r in entity_rows
    ]

    async with conn.cursor() as cur:
        if direction and hops == 1:
            group_cols = "source_entity_id, target_entity_id"
            if direction == "incoming":
                await cur.execute(
                    f"""
                    SELECT MIN(id), source_entity_id, target_entity_id,
                           CASE WHEN COUNT(DISTINCT edge_type) = 1 THEN MIN(edge_type) ELSE 'multiple' END,
                           SUM(amount), MAX(date),
                           CASE WHEN COUNT(DISTINCT state) = 1 THEN MIN(state) ELSE NULL END,
                           NULL
                    FROM unified.official_edges
                    WHERE target_entity_id = %s AND source_entity_id = ANY(%s::int[])
                    GROUP BY {group_cols}
                    ORDER BY SUM(COALESCE(amount, 0)) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (entity_id, all_node_ids, max_edges),
                )
            else:
                await cur.execute(
                    f"""
                    SELECT MIN(id), source_entity_id, target_entity_id,
                           CASE WHEN COUNT(DISTINCT edge_type) = 1 THEN MIN(edge_type) ELSE 'multiple' END,
                           SUM(amount), MAX(date),
                           CASE WHEN COUNT(DISTINCT state) = 1 THEN MIN(state) ELSE NULL END,
                           NULL
                    FROM unified.official_edges
                    WHERE source_entity_id = %s AND target_entity_id = ANY(%s::int[])
                    GROUP BY {group_cols}
                    ORDER BY SUM(COALESCE(amount, 0)) DESC NULLS LAST
                    LIMIT %s
                    """,
                    (entity_id, all_node_ids, max_edges),
                )
        else:
            await cur.execute(
                """
                SELECT id, source_entity_id, target_entity_id, edge_type,
                       amount, date, state, description
                FROM unified.official_edges
                WHERE source_entity_id = ANY(%s::int[])
                  AND target_entity_id = ANY(%s::int[])
                ORDER BY amount DESC NULLS LAST
                LIMIT %s
                """,
                (all_node_ids, all_node_ids, max_edges),
            )
        edge_rows = await cur.fetchall()

    edges = [
        GraphEdge(
            id=r[0], source_entity_id=r[1], target_entity_id=r[2], edge_type=r[3],
            amount=float(r[4]) if r[4] is not None else None,
            date=r[5].isoformat() if r[5] is not None else None,
            state=r[6], description=r[7],
        )
        for r in edge_rows
    ]

    inferred: Optional[list[InferredEdge]] = None
    if include_inferred:
        async with conn.cursor() as cur:
            await cur.execute(
                _INFERRED_SELECT
                + "WHERE seed_entity_id = ANY(%s::int[]) OR target_entity_id = ANY(%s::int[])"
                + _INFERRED_ORDER,
                (all_node_ids, all_node_ids),
            )
            inferred = [_build_inferred_edge(r) for r in await cur.fetchall()]

    return Neighborhood(seed_entity_id=entity_id, hops=hops, nodes=nodes, edges=edges, inferred_edges=inferred)


@router.get("/entities/{entity_id}/profile", response_model=EntityProfile)
async def get_entity_profile(entity_id: int):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, canonical_name, entity_type, state, city, state_code, zip5,
                   COALESCE(mention_count, 0)
            FROM unified.entities WHERE id = %s
            """,
            (entity_id,),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    entity = EntityInfo(
        id=row[0], name=row[1], type=row[2], state=row[3],
        city=row[4], state_code=row[5], zip5=row[6], mention_count=row[7],
    )

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                SUM(CASE WHEN target_entity_id = %s THEN COALESCE(amount, 0) ELSE 0 END),
                COUNT(CASE WHEN target_entity_id = %s THEN 1 END),
                COUNT(DISTINCT CASE WHEN target_entity_id = %s THEN source_entity_id END),
                SUM(CASE WHEN source_entity_id = %s THEN COALESCE(amount, 0) ELSE 0 END),
                COUNT(CASE WHEN source_entity_id = %s THEN 1 END),
                COUNT(DISTINCT CASE WHEN source_entity_id = %s THEN target_entity_id END)
            FROM unified.official_edges
            WHERE source_entity_id = %s OR target_entity_id = %s
            """,
            (entity_id,) * 8,
        )
        stats = await cur.fetchone()

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM (
                SELECT oe.id, 'incoming' AS direction, oe.source_entity_id,
                       e.canonical_name, e.entity_type, oe.edge_type,
                       oe.amount, oe.date, oe.state, oe.description
                FROM unified.official_edges oe
                JOIN unified.entities e ON e.id = oe.source_entity_id
                WHERE oe.target_entity_id = %s
                ORDER BY oe.date DESC NULLS LAST LIMIT 20
            ) incoming
            UNION ALL
            SELECT * FROM (
                SELECT oe.id, 'outgoing' AS direction, oe.target_entity_id,
                       e.canonical_name, e.entity_type, oe.edge_type,
                       oe.amount, oe.date, oe.state, oe.description
                FROM unified.official_edges oe
                JOIN unified.entities e ON e.id = oe.target_entity_id
                WHERE oe.source_entity_id = %s
                ORDER BY oe.date DESC NULLS LAST LIMIT 20
            ) outgoing
            """,
            (entity_id, entity_id),
        )
        recent_edges = [
            RecentEdge(
                edge_id=r[0], direction=r[1], counterparty_entity_id=r[2],
                counterparty_name=r[3], counterparty_type=r[4], edge_type=r[5],
                amount=float(r[6]) if r[6] is not None else None,
                date=r[7].isoformat() if r[7] is not None else None,
                state=r[8], description=r[9],
            )
            for r in await cur.fetchall()
        ]

    return EntityProfile(
        entity=entity,
        finance=Finance(
            incoming_total=float(stats[0] or 0),
            incoming_count=int(stats[1] or 0),
            unique_sources=int(stats[2] or 0),
            outgoing_total=float(stats[3] or 0),
            outgoing_count=int(stats[4] or 0),
            unique_targets=int(stats[5] or 0),
            recent_edges=recent_edges,
        ),
    )


@router.get("/entities/{entity_id}/inferred", response_model=InferredEdgesResponse)
async def get_inferred_edges(entity_id: int):
    conn = await db()

    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM unified.entities WHERE id = %s", (entity_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    async with conn.cursor() as cur:
        await cur.execute(
            _INFERRED_SELECT + "WHERE seed_entity_id = %s OR target_entity_id = %s" + _INFERRED_ORDER,
            (entity_id, entity_id),
        )
        rows = await cur.fetchall()

    return InferredEdgesResponse(entity_id=entity_id, inferred_edges=[_build_inferred_edge(r) for r in rows])


@router.delete("/inferred", status_code=200)
async def delete_inferred():
    conn = await db()
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM unified.inferred_edges")
        edges_deleted = cur.rowcount
        await cur.execute(
            "DELETE FROM unified.entities WHERE run_id = %s",
            (get_agent_inferred_run_id(),),
        )
        entities_deleted = cur.rowcount
    return {"edges_deleted": edges_deleted, "entities_deleted": entities_deleted}
