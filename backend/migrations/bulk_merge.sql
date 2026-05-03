BEGIN;

-- Build merge map using window functions — avoids the slow EXISTS correlated subquery
CREATE TEMP TABLE _merge_map AS
SELECT id AS discard_id, keep_id
FROM (
    SELECT
        id,
        first_value(id) OVER w AS keep_id,
        COUNT(*) OVER (PARTITION BY normalized_name, state) AS cnt
    FROM unified.entities
    WINDOW w AS (
        PARTITION BY normalized_name, state
        ORDER BY COALESCE(mention_count, 0) DESC, id ASC
    )
) sub
WHERE cnt > 1 AND id <> keep_id;

CREATE INDEX ON _merge_map (discard_id);
CREATE INDEX ON _merge_map (keep_id);

-- 1. Sum mention_counts onto keep entities before deleting anything
UPDATE unified.entities e
SET mention_count = e.mention_count + agg.extra
FROM (
    SELECT keep_id, SUM(COALESCE(d.mention_count, 0)) AS extra
    FROM _merge_map mm
    JOIN unified.entities d ON d.id = mm.discard_id
    GROUP BY keep_id
) agg
WHERE e.id = agg.keep_id;

-- 2. Remap official_edges source
UPDATE unified.official_edges oe
SET source_entity_id = mm.keep_id
FROM _merge_map mm
WHERE oe.source_entity_id = mm.discard_id;

-- 3. Remap official_edges target
UPDATE unified.official_edges oe
SET target_entity_id = mm.keep_id
FROM _merge_map mm
WHERE oe.target_entity_id = mm.discard_id;

-- 4. Delete self-edges
DELETE FROM unified.official_edges
WHERE source_entity_id = target_entity_id;

-- 5. Deduplicate edges — ROW_NUMBER() is much faster than NOT IN
DELETE FROM unified.official_edges a
USING (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY source_entity_id, target_entity_id, source_table, source_row_id
               ORDER BY id
           ) AS rn
    FROM unified.official_edges
    WHERE source_row_id IS NOT NULL
) b
WHERE a.id = b.id AND b.rn > 1;

-- 6. Remap inferred_edges seed + target
UPDATE unified.inferred_edges ie
SET seed_entity_id = mm.keep_id
FROM _merge_map mm
WHERE ie.seed_entity_id = mm.discard_id;

UPDATE unified.inferred_edges ie
SET target_entity_id = mm.keep_id
FROM _merge_map mm
WHERE ie.target_entity_id = mm.discard_id;

DELETE FROM unified.inferred_edges WHERE seed_entity_id = target_entity_id;

DELETE FROM unified.inferred_edges
WHERE id NOT IN (
    SELECT MIN(id) FROM unified.inferred_edges
    GROUP BY seed_entity_id, target_entity_id, relationship_type
);

-- 7. Remap entity_mentions (has index on entity_id — fast)
UPDATE unified.entity_mentions em
SET entity_id = mm.keep_id
FROM _merge_map mm
WHERE em.entity_id = mm.discard_id;

-- 8. Delete enrichments for discarded entities
DELETE FROM unified.entity_enrichments
WHERE entity_id IN (SELECT discard_id FROM _merge_map);

-- 9. Delete discarded entities
DELETE FROM unified.entities
WHERE id IN (SELECT discard_id FROM _merge_map);

COMMIT;
