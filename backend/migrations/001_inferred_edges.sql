CREATE TABLE IF NOT EXISTS unified.inferred_edges (
    id bigserial PRIMARY KEY,
    seed_entity_id integer REFERENCES unified.entities(id),
    seed_entity_name text,
    target_name text NOT NULL,
    target_entity_id integer REFERENCES unified.entities(id),
    target_type text,
    relationship_type text,
    evidence_quotes text[],
    source_urls text[],
    source_domains text[],
    evidence_strength text CHECK (evidence_strength IN ('direct', 'indirect', 'weak')),
    found_by text[],
    depth integer DEFAULT 1,
    found_from text,
    verified boolean DEFAULT false,
    created_at timestamptz DEFAULT now(),
    run_id text
);

CREATE INDEX IF NOT EXISTS inferred_edges_seed_idx
    ON unified.inferred_edges (seed_entity_id);
CREATE INDEX IF NOT EXISTS inferred_edges_target_entity_idx
    ON unified.inferred_edges (target_entity_id);
CREATE INDEX IF NOT EXISTS inferred_edges_run_idx
    ON unified.inferred_edges (run_id);
