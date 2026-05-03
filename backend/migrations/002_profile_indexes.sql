-- Speeds up /entities/{entity_id}/profile lookups.
-- The endpoint repeatedly filters official_edges by source_entity_id or target_entity_id,
-- then orders by amount/date for sidebar tables.

CREATE INDEX IF NOT EXISTS official_edges_target_entity_idx
    ON unified.official_edges (target_entity_id);

CREATE INDEX IF NOT EXISTS official_edges_source_entity_idx
    ON unified.official_edges (source_entity_id);

CREATE INDEX IF NOT EXISTS official_edges_target_amount_idx
    ON unified.official_edges (target_entity_id, amount DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS official_edges_source_amount_idx
    ON unified.official_edges (source_entity_id, amount DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS official_edges_target_date_idx
    ON unified.official_edges (target_entity_id, date DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS official_edges_source_date_idx
    ON unified.official_edges (source_entity_id, date DESC NULLS LAST);
