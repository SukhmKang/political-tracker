import dagre from "dagre";
import { MarkerType } from "@xyflow/react";
import type {
  ApiGraphEdge,
  ApiGraphNode,
  AppEdge,
  AppNode,
  DegreeCounts,
  EntityProfile,
  EntityStatus,
  ExpansionRecord,
  InferredEdge,
} from "./types";
import { titleize } from "./format";

export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 92;
export const GRID_THRESHOLD = 8;
export const GRID_COLUMNS = 3;
export const GRID_COLUMN_GAP = 250;
export const GRID_ROW_GAP = 116;
export const EXPANSION_LIMIT_THRESHOLD = 12;

export function entityNodeId(id: number | string): string {
  return `entity-${id}`;
}

export function expansionKey(entityId: number, direction: "incoming" | "outgoing"): string {
  return `${entityId}:${direction}`;
}

export function makeEntityNode(
  entity: Pick<ApiGraphNode, "name" | "type" | "state" | "mention_count"> & { id: number; depth?: number },
  status: EntityStatus,
): AppNode {
  return {
    id: entityNodeId(entity.id),
    type: "entity",
    position: { x: 0, y: 0 },
    draggable: true,
    data: {
      kind: "entity",
      entityId: entity.id,
      label: entity.name ?? `Entity ${entity.id}`,
      subtitle:
        [titleize(entity.type), titleize(entity.state)].filter(Boolean).join(" · ") || `${entity.mention_count} mentions`,
      status,
    },
  };
}

export function makeEdge(edge: ApiGraphEdge): AppEdge {
  return {
    id: `official-${edge.id}`,
    source: entityNodeId(edge.source_entity_id),
    target: entityNodeId(edge.target_entity_id),
    type: "bezier",
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#64748b" },
    style: { stroke: "#64748b", strokeWidth: 1.8 },
    data: { amount: edge.amount, status: "verified", label: "" },
  };
}

export function makeInferredEdge(edge: InferredEdge, originEntityId: number): AppEdge {
  return {
    id: `inferred-${originEntityId}-${edge.id}`,
    source: entityNodeId(edge.seed_entity_id ?? originEntityId),
    target: entityNodeId(edge.target_entity_id ?? `inferred-${edge.id}`),
    type: "exaRelationship",
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#d97706" },
    style: { stroke: "#d97706", strokeWidth: 1.8, strokeDasharray: "6 4" },
    data: { amount: null, status: "inferred", inferredEdges: [edge] },
  };
}

export function mergeNodes(nodes: AppNode[]): AppNode[] {
  return Array.from(new Map(nodes.map((node) => [node.id, node])).values());
}

export function mergeEdges(edges: AppEdge[]): AppEdge[] {
  const merged = new Map<string, AppEdge>();

  edges.forEach((edge) => {
    const status = String(edge.data?.status ?? "verified");
    const key = `${status}:${edge.source}->${edge.target}`;
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, {
        ...edge,
        id: key,
      });
      return;
    }

    const existingAmount = typeof existing.data?.amount === "number" ? existing.data.amount : 0;
    const nextAmount = typeof edge.data?.amount === "number" ? edge.data.amount : 0;
    const existingInferredEdges = existing.data?.inferredEdges ?? [];
    const nextInferredEdges = edge.data?.inferredEdges ?? [];
    merged.set(key, {
      ...existing,
      data: {
        ...existing.data,
        status: existing.data?.status ?? (status === "inferred" ? "inferred" : "verified"),
        amount: existingAmount + nextAmount,
        inferredEdges: [...existingInferredEdges, ...nextInferredEdges],
      },
    });
  });

  return Array.from(merged.values());
}

export function countsFromProfile(profile: EntityProfile): DegreeCounts {
  return {
    incoming: profile.finance.unique_sources ?? profile.finance.incoming_count ?? 0,
    outgoing: profile.finance.unique_targets ?? profile.finance.outgoing_count ?? 0,
  };
}

export function layoutGraph(nodes: AppNode[], edges: AppEdge[], expansions: ExpansionRecord[]): AppNode[] {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: "LR",
    align: "UL",
    nodesep: 44,
    ranksep: 72,
    marginx: 32,
    marginy: 32,
  });

  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((edge) => {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) graph.setEdge(edge.source, edge.target);
  });

  dagre.layout(graph);

  const layouted = nodes.map((node) => {
    const positioned = graph.node(node.id);
    if (!positioned) return node;
    return {
      ...node,
      position: {
        x: positioned.x - NODE_WIDTH / 2,
        y: positioned.y - NODE_HEIGHT / 2,
      },
    };
  });

  return gridLargeExpansions(layouted, expansions);
}

function gridLargeExpansions(nodes: AppNode[], expansions: ExpansionRecord[]): AppNode[] {
  const visibleNodeIds = new Set(nodes.map((node) => node.id));
  const nextPositions = new Map(nodes.map((node) => [node.id, node.position]));
  const collides = (
    proposed: Array<{ x: number; y: number }>,
    existing: Array<{ x: number; y: number }>,
    shiftY: number,
  ) => {
    const padding = 14;
    return proposed.some((position) =>
      existing.some((other) => {
        const left = position.x;
        const right = position.x + NODE_WIDTH;
        const top = position.y + shiftY;
        const bottom = position.y + shiftY + NODE_HEIGHT;
        const otherLeft = other.x;
        const otherRight = other.x + NODE_WIDTH;
        const otherTop = other.y;
        const otherBottom = other.y + NODE_HEIGHT;

        return (
          left < otherRight + padding &&
          right + padding > otherLeft &&
          top < otherBottom + padding &&
          bottom + padding > otherTop
        );
      }),
    );
  };

  expansions
    .filter((expansion) => expansion.nodeCount > GRID_THRESHOLD)
    .forEach((expansion) => {
      const originId = entityNodeId(expansion.originEntityId);
      const originPosition = nextPositions.get(originId);
      if (!originPosition) return;

      const childIds = expansion.edges
        .map((edge) => {
          if (edge.source === originId) return edge.target;
          if (edge.target === originId) return edge.source;
          return null;
        })
        .filter((nodeId): nodeId is string => Boolean(nodeId && visibleNodeIds.has(nodeId)));

      const uniqueChildIds = Array.from(new Set(childIds));
      if (uniqueChildIds.length <= GRID_THRESHOLD) return;

      const rows = Math.ceil(uniqueChildIds.length / GRID_COLUMNS);
      const totalHeight = Math.max(0, rows - 1) * GRID_ROW_GAP;
      const startY = originPosition.y + NODE_HEIGHT / 2 - totalHeight / 2 - NODE_HEIGHT / 2;
      const xSign = expansion.direction === "incoming" ? -1 : 1;

      const proposedPositions = uniqueChildIds.map((nodeId, index) => {
        const col = index % GRID_COLUMNS;
        const row = Math.floor(index / GRID_COLUMNS);
        const x =
          expansion.direction === "incoming"
            ? originPosition.x - GRID_COLUMN_GAP * (col + 1)
            : originPosition.x + GRID_COLUMN_GAP * (col + 1);

        return {
          nodeId,
          x: x + xSign * Math.floor(row / 9) * 24,
          y: startY + row * GRID_ROW_GAP,
        };
      });
      const childIdSet = new Set(uniqueChildIds);
      const existingPositions = Array.from(nextPositions.entries())
        .filter(([nodeId]) => nodeId !== originId && !childIdSet.has(nodeId))
        .map(([, position]) => position);
      const shiftCandidates = Array.from({ length: 18 }, (_, index) => {
        if (index === 0) return 0;
        const steps = Math.ceil(index / 2);
        return (index % 2 === 1 ? 1 : -1) * steps * GRID_ROW_GAP;
      });
      const proposedOnly = proposedPositions.map(({ x, y }) => ({ x, y }));
      const shiftY = shiftCandidates.find((shift) => !collides(proposedOnly, existingPositions, shift)) ?? 0;

      proposedPositions.forEach(({ nodeId, x, y }) => {
        nextPositions.set(nodeId, { x, y: y + shiftY });
      });
    });

  return nodes.map((node) => ({
    ...node,
    position: nextPositions.get(node.id) ?? node.position,
  }));
}
