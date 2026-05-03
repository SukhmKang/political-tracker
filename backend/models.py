from typing import Optional
from pydantic import BaseModel


class EntityInfo(BaseModel):
    id: int
    name: Optional[str]
    type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    state_code: Optional[str]
    zip5: Optional[str]
    mention_count: int


class EntitySearchResult(BaseModel):
    id: int
    name: Optional[str]
    type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    state_code: Optional[str]
    zip5: Optional[str]
    mention_count: int
    score: float


class CounterpartyEntry(BaseModel):
    entity_id: int
    name: Optional[str]
    type: Optional[str]
    total_amount: float
    edge_count: int


class RecentEdge(BaseModel):
    edge_id: int
    direction: str
    counterparty_entity_id: int
    counterparty_name: Optional[str]
    counterparty_type: Optional[str]
    edge_type: str
    amount: Optional[float]
    date: Optional[str]
    state: Optional[str]
    description: Optional[str]


class Finance(BaseModel):
    incoming_total: float
    outgoing_total: float
    incoming_count: int
    outgoing_count: int
    unique_sources: int
    unique_targets: int
    top_sources: list[CounterpartyEntry]
    top_targets: list[CounterpartyEntry]
    recent_edges: list[RecentEdge]


class EntityProfile(BaseModel):
    entity: EntityInfo
    finance: Finance


class GraphNode(BaseModel):
    id: int
    name: Optional[str]
    type: Optional[str]
    state: Optional[str]
    mention_count: int
    depth: int


class GraphEdge(BaseModel):
    id: int
    source_entity_id: int
    target_entity_id: int
    edge_type: str
    amount: Optional[float]
    date: Optional[str]
    state: Optional[str]
    description: Optional[str]


class InferredEdge(BaseModel):
    id: int
    target_name: str
    target_entity_id: Optional[int]
    target_type: Optional[str]
    relationship_type: Optional[str]
    evidence_quotes: list[str]
    source_urls: list[str]
    source_domains: list[str]
    evidence_strength: Optional[str]
    found_by: list[str]
    verified: bool
    created_at: str


class InferredEdgesResponse(BaseModel):
    entity_id: int
    inferred_edges: list[InferredEdge]


class Neighborhood(BaseModel):
    seed_entity_id: int
    hops: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    inferred_edges: Optional[list[InferredEdge]] = None


class NewsItem(BaseModel):
    headline: str
    url: str
    date: Optional[str]
    summary: str


class EnrichmentSource(BaseModel):
    url: str
    domain: str
    used_for: Optional[str]


class EntityEnrichment(BaseModel):
    id: int
    entity_id: int
    enriched_at: str
    entity_type: Optional[str]
    description: Optional[str]
    occupation: Optional[str]
    employer: Optional[str]
    political_party: Optional[str]
    office_held: Optional[str]
    mission: Optional[str]
    founded_year: Optional[str]
    jurisdiction: Optional[str]
    recent_news: list[NewsItem]
    sources: list[EnrichmentSource]


class DiscoverRequest(BaseModel):
    entity_name: str
    depth: int = 1
    max_expand: int = 3


class DiscoverResponse(BaseModel):
    run_id: str
    seed_entity_id: Optional[int]
    seed_entity_name: str
    connections_found: int
    verified_count: int
    inferred_count: int


class MergeCandidateEntity(BaseModel):
    id: int
    canonical_name: Optional[str]
    entity_type: Optional[str]
    mention_count: int
    run_name: Optional[str]


class MergeCandidateGroup(BaseModel):
    normalized_name: str
    state: Optional[str]
    entity_count: int
    keep_id: int
    discard_ids: list[int]
    total_mentions: int
    entities: list[MergeCandidateEntity]


class MergeCandidatesResponse(BaseModel):
    total_groups: int
    total_would_delete: int
    sample_groups: list[MergeCandidateGroup]


class BulkMergeOperation(BaseModel):
    keep_id: int
    discard_ids: list[int]


class BulkMergeRequest(BaseModel):
    merges: list[BulkMergeOperation]


class BulkMergeResponse(BaseModel):
    groups_processed: int
    entities_deleted: int
    official_edges_remapped: int
    self_edges_deleted: int
    duplicate_edges_deleted: int
    inferred_edges_remapped: int
    mentions_remapped: int
    enrichments_deleted: int


class MergeRequest(BaseModel):
    keep_id: int
    discard_ids: list[int]


class MergeResponse(BaseModel):
    kept_id: int
    discarded_ids: list[int]
    edges_remapped: int
    self_edges_deleted: int
    duplicate_edges_deleted: int
    mentions_remapped: int
    enrichments_deleted: int
