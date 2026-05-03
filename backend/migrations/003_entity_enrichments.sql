CREATE TABLE IF NOT EXISTS unified.entity_enrichments (
    id bigserial PRIMARY KEY,
    entity_id integer NOT NULL REFERENCES unified.entities(id),
    enriched_at timestamptz DEFAULT now(),
    entity_type text,
    description text,
    occupation text,
    employer text,
    political_party text,
    office_held text,
    mission text,
    founded_year text,
    jurisdiction text,
    recent_news jsonb DEFAULT '[]',
    sources jsonb DEFAULT '[]',
    raw_output jsonb
);

CREATE INDEX IF NOT EXISTS entity_enrichments_entity_idx
    ON unified.entity_enrichments (entity_id, enriched_at DESC);
