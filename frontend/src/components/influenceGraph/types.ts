import type { Edge, Node } from "@xyflow/react";

export type Direction = "incoming" | "outgoing";
export type EntityStatus = "verified" | "inferred";
export type AppNode = Node<EntityNodeData>;
export type AppEdge = Edge<AppEdgeData>;

export interface InfluenceGraphProps {
  entityId: number;
}

export interface ApiGraphNode {
  id: number;
  name: string | null;
  type: string | null;
  state: string | null;
  mention_count: number;
  depth: number;
}

export interface ApiGraphEdge {
  id: number;
  source_entity_id: number;
  target_entity_id: number;
  edge_type: string;
  amount: number | null;
  date: string | null;
  state: string | null;
  description: string | null;
}

export interface ApiInferredEdge {
  id: number;
  seed_entity_id?: number | null;
  seed_entity_name?: string | null;
  target_name: string;
  target_entity_id: number | null;
  target_type: string | null;
  relationship_type: string | null;
  evidence_quotes: string[];
  source_urls: string[];
  source_domains: string[];
  evidence_strength: string | null;
  found_by: string[];
  depth?: number;
  found_from?: string | null;
  verified: boolean;
  created_at: string;
}

export interface NeighborhoodResponse {
  seed_entity_id: number;
  nodes: ApiGraphNode[];
  edges: ApiGraphEdge[];
  inferred_edges?: ApiInferredEdge[] | null;
}

export interface DiscoverResponse {
  run_id: string;
  seed_entity_id: number | null;
  seed_entity_name: string;
  connections_found: number;
  verified_count: number;
  inferred_count: number;
  inferred_edges: ApiInferredEdge[];
}

export interface RecentEdge {
  edge_id: number;
  direction: Direction;
  counterparty_entity_id: number;
  counterparty_name: string | null;
  counterparty_type: string | null;
  edge_type: string;
  amount: number | null;
  date: string | null;
  state: string | null;
  description: string | null;
}

export interface EntityProfile {
  entity: {
    id: number;
    name: string | null;
    type: string | null;
    state: string | null;
    city: string | null;
    state_code: string | null;
    zip5: string | null;
    mention_count: number;
  };
  finance: {
    incoming_total?: number | null;
    outgoing_total?: number | null;
    incoming_count?: number;
    outgoing_count?: number;
    unique_sources?: number;
    unique_targets?: number;
    recent_edges: RecentEdge[];
  };
}

export interface NewsItem {
  headline: string;
  url: string;
  date: string | null;
  summary: string;
}

export interface EnrichmentSource {
  url: string;
  domain: string;
  used_for: string;
}

export interface EntityEnrichment {
  id: number;
  entity_id: number;
  enriched_at: string;
  entity_type: string | null;
  description: string | null;
  occupation: string | null;
  employer: string | null;
  political_party: string | null;
  office_held: string | null;
  mission: string | null;
  founded_year: string | null;
  jurisdiction: string | null;
  recent_news: NewsItem[];
  sources: EnrichmentSource[];
}

export interface EntityNodeData extends Record<string, unknown> {
  kind: "entity";
  entityId: number;
  label: string;
  subtitle: string;
  status: EntityStatus;
  incomingLoaded?: boolean;
  outgoingLoaded?: boolean;
  incomingCount?: number;
  outgoingCount?: number;
  loadingDirection?: Direction | null;
  onToggleDirection?: (entityId: number, direction: Direction, limit?: number) => void;
}

export interface InferredEdge extends ApiInferredEdge {
  seed_entity_id?: number;
}

export interface RelationshipDetail {
  edge: InferredEdge;
  summary: string;
}

export interface AppEdgeData extends Record<string, unknown> {
  amount: number | null;
  status: EntityStatus;
  label?: string;
  inferredEdges?: InferredEdge[];
  relationshipDetails?: RelationshipDetail[];
  onOpenDetails?: (details: RelationshipDetail[]) => void;
}

export interface ExpansionRecord {
  originEntityId: number;
  direction: Direction;
  nodes: AppNode[];
  edges: AppEdge[];
  inferredEdges: InferredEdge[];
  nodeCount: number;
}

export interface DegreeCounts {
  incoming: number;
  outgoing: number;
}
