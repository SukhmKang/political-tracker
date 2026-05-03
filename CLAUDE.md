# State Political Tracker — Demo

## What this is

A campaign finance graph built from state disclosure data. It tracks who gave money to whom across 19 states, resolving donors, recipients, committees, and vendors into deduplicated entities and linking them through financial transactions.

## Database

Local Postgres. Connection string in `backend/.env` as `DB_URL`.

## States covered

Alabama, Arkansas, Colorado, Indiana, Iowa, Kentucky, Maryland, Michigan, Minnesota, Missouri, Nebraska, New York, Ohio, Pennsylvania, Tennessee, Texas, Virginia, West Virginia, Wisconsin.

## Amount threshold

All transactions under **$1,000** have been filtered out. The dataset intentionally focuses on significant recurring relationships rather than one-time small donors.

## Data pipeline (simplified)

```
raw state tables (ohio.*, indiana.*, ...)
        ↓
unified.contributions + unified.expenditures   ← cleaned, normalized, cross-state
        ↓
unified.entity_mentions                        ← one row per entity role per transaction
        ↓
unified.entities                               ← deduplicated entities (deterministic_v1)
        ↓
unified.official_edges                         ← graph edges, one per transaction
```

Post-pipeline, a bulk entity merge was run to collapse duplicate entities (same `normalized_name` + `state`) down to a single canonical row, consolidating `mention_count` and remapping all edges. ~243k duplicates were removed.

## Key tables

### `unified.contributions`
One row per contribution filing. Columns include: `id`, `state`, `source_table`, `source_id`, `amount`, `date`, `contributor_name`, `contributor_type_canonical`, `contributor_state`, `contributor_zip`, `recipient_name`, `recipient_type_canonical`, `transaction_type`, `is_inkind`.

### `unified.expenditures`
One row per expenditure filing. Columns include: `id`, `state`, `source_table`, `source_id`, `amount`, `date`, `committee_name`, `committee_type_canonical`, `payee_name`, `payee_type_canonical`, `purpose`, `expenditure_type`, `is_independent`.

### `unified.entity_mentions`
Every time an entity appears in a transaction — as contributor, recipient, committee, or payee. Columns include: `id`, `state`, `source_table`, `source_row_id`, `role`, `raw_name`, `normalized_name`, `entity_type`, `zip5`, `entity_id`.

### `unified.entities`
Deduplicated entities. ~1.3M rows after the post-pipeline merge pass. Columns include: `id`, `run_id`, `cluster_key`, `entity_type`, `canonical_name`, `normalized_name`, `state`, `city`, `zip5`, `mention_count`.

`run_id` is a FK to `unified.entity_resolution_runs`. The active pipeline run is `deterministic_v1` (id=2). Agent-created entities use `agent_inferred` (id=3, upserted at startup).

Entity types: `individual`, `organization`, `committee`, `candidate`, `party`, `government`.

### `unified.official_edges`
The graph edges. ~2.7M rows. One row per transaction. Columns include: `id`, `source_entity_id`, `target_entity_id`, `edge_type`, `amount`, `date`, `state`, `source_table`, `source_row_id`, `description`, `purpose`, `transaction_type`, `expenditure_type`, `is_inkind`, `is_independent`.

Edge types:
- `contributed_to` — contributor → recipient (~1.1M edges, ~$8B)
- `paid` — committee → payee (~1.7M edges, ~$13B)

### `unified.inferred_edges`
Agent-discovered relationships. One row per connection found by the discovery agent. Columns include: `id`, `seed_entity_id`, `seed_entity_name`, `target_name`, `target_entity_id`, `target_type`, `relationship_type` (plain-English sentence), `evidence_quotes`, `source_urls`, `source_domains`, `evidence_strength`, `found_by`, `depth`, `found_from`, `verified`, `run_id`, `created_at`.

### `unified.entity_enrichments`
Exa-researched metadata per entity. One row per enrichment run (re-runnable). Columns include: `id`, `entity_id`, `enriched_at`, `entity_type`, `description`, `occupation`, `employer`, `political_party`, `office_held`, `mission`, `founded_year`, `jurisdiction`, `recent_news` (jsonb), `sources` (jsonb), `raw_output` (jsonb).

Fields populated vary by entity type:
- `individual`: description, occupation, employer, political_party
- `candidate`: description, occupation, political_party, office_held
- `committee`: description, mission, political_party
- `organization`: description, mission, founded_year
- `government`: description, office_held, jurisdiction

### Supporting tables
- `unified.entity_resolution_runs` — tracks resolution run metadata
- `unified.entity_resolution_assignments` — maps each entity_mention to its cluster (uses `cluster_key`, not entity id)

## Backend structure

```
backend/
  main.py            — FastAPI app setup, middleware, router includes
  db.py              — connection pool, lifespan, db() helper, gemini client
  models.py          — all Pydantic models
  agent.py           — Exa-powered discovery agent (parallel subagents + synthesizer)
  enrich.py          — Exa-powered enrichment agent (bio, news, political subagents)
  search_tools.py    — shared Exa search function_tools (web_search, multi_search, opensecrets_search, fec_search, influencewatch_search, propublica_search)
  routes/
    entities.py      — search, neighborhood, profile, inferred edges endpoints
    discover.py      — /discover endpoint + entity resolution helpers
    enrichment.py    — enrich, get enrichment, delete enrichment endpoints
    merge.py         — merge candidates, bulk merge, single merge endpoints
  migrations/
    001_inferred_edges.sql
    002_profile_indexes.sql
    003_entity_enrichments.sql
```

## API endpoints

### Entities
- `GET /entities/search?q=...` — fuzzy entity search
- `GET /entities/{id}/profile` — finance summary, top sources/targets, recent edges
- `GET /entities/{id}/neighborhood` — graph subgraph (BFS, supports `direction=incoming|outgoing`, `hops`, `max_nodes`, `max_edges`, `include_inferred`)
- `GET /entities/{id}/inferred` — agent-discovered connections for an entity
- `DELETE /inferred` — clear all inferred edges and agent-created entities

### Discovery (Exa agent)
- `POST /discover` — run the multi-subagent discovery pipeline on an entity name

### Enrichment (Exa agent)
- `POST /entities/{id}/enrich` — run enrichment agent, store and return result
- `GET /entities/{id}/enrichment` — fetch most recent stored enrichment
- `DELETE /entities/{id}/enrichment` — delete stored enrichment

### Merge / deduplication
- `GET /entities/merge-candidates` — find duplicate entity groups (exact normalized_name + state match), returns totals + samples
- `POST /entities/merge` — merge a single group `{keep_id, discard_ids}`
- `POST /entities/merge-bulk` — merge many groups at once via temp table (efficient for large batches)

## Merge operation order

When merging entities, always follow this order to avoid FK violations:
1. Sum `mention_count` onto keep entity
2. Remap `official_edges` source + target
3. Delete self-edges
4. Deduplicate edges by `(source, target, source_table, source_row_id)`
5. Remap `inferred_edges` seed + target
6. Remap `entity_mentions.entity_id` (no FK constraint, logical reference)
7. Delete enrichments for discarded entities
8. Delete discarded entities

## Useful queries

```sql
-- Total edges by type
SELECT edge_type, COUNT(*), SUM(amount) FROM unified.official_edges GROUP BY edge_type;

-- Top donors
SELECT e.canonical_name, e.entity_type, SUM(oe.amount) AS total_out
FROM unified.official_edges oe
JOIN unified.entities e ON e.id = oe.source_entity_id
WHERE oe.edge_type = 'contributed_to'
GROUP BY e.id, e.canonical_name, e.entity_type
ORDER BY total_out DESC LIMIT 20;

-- All edges for a specific entity
SELECT oe.*, es.canonical_name AS source, et.canonical_name AS target
FROM unified.official_edges oe
JOIN unified.entities es ON es.id = oe.source_entity_id
JOIN unified.entities et ON et.id = oe.target_entity_id
WHERE es.canonical_name ILIKE '%search term%'
   OR et.canonical_name ILIKE '%search term%'
LIMIT 50;

-- Entity lookup
SELECT * FROM unified.entities
WHERE normalized_name ILIKE '%search term%'
ORDER BY mention_count DESC LIMIT 20;

-- Find remaining duplicate entity groups
SELECT normalized_name, state, COUNT(*) AS copies
FROM unified.entities
GROUP BY normalized_name, state
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC LIMIT 20;
```
