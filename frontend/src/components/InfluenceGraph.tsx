import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, ReactFlow, applyNodeChanges, type NodeChange, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./influenceGraph/InfluenceGraph.css";
import { apiGet, apiGetOptional, apiPost } from "./influenceGraph/api";
import { edgeTypes, nodeTypes } from "./influenceGraph/GraphElements";
import {
  ExaSearchNotice,
  GraphEmptyOverlay,
  GraphLegend,
  GraphLoadingOverlay,
  GraphToolbar,
  NodeContextMenu,
  RelationshipDetailsModal,
} from "./influenceGraph/GraphChrome";
import { formatCompactMoney, relationshipSummary, titleize } from "./influenceGraph/format";
import {
  countsFromProfile,
  entityNodeId,
  expansionKey,
  layoutGraph,
  makeEdge,
  makeEntityNode,
  makeInferredEdge,
  mergeEdges,
  mergeNodes,
} from "./influenceGraph/model";
import { Sidebar } from "./influenceGraph/Sidebar";
import type {
  AppEdge,
  AppNode,
  DegreeCounts,
  Direction,
  EntityEnrichment,
  EntityProfile,
  ExpansionRecord,
  InfluenceGraphProps,
  InferredEdge,
  InferredResponse,
  NeighborhoodResponse,
  RelationshipDetail,
} from "./influenceGraph/types";

function edgeLinkedExpansionNodeIds(originEntityId: number, edges: AppEdge[]) {
  const originNodeId = entityNodeId(originEntityId);
  const linkedNodeIds = new Set<string>([originNodeId]);

  edges.forEach((edge) => {
    if (edge.source === originNodeId) linkedNodeIds.add(edge.target);
    if (edge.target === originNodeId) linkedNodeIds.add(edge.source);
  });

  return linkedNodeIds;
}

function countExpansionNeighbors(originEntityId: number, edges: AppEdge[]) {
  return Math.max(0, edgeLinkedExpansionNodeIds(originEntityId, edges).size - 1);
}

export default function InfluenceGraph({ entityId }: InfluenceGraphProps) {
  const [baseNode, setBaseNode] = useState<AppNode | null>(null);
  const [expansions, setExpansions] = useState<Record<string, ExpansionRecord>>({});
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(entityId);
  const [showInferred, setShowInferred] = useState(true);
  const [loadingExpansion, setLoadingExpansion] = useState<{ entityId: number; direction: Direction } | null>(null);
  const [searchingExa, setSearchingExa] = useState(false);
  const [profile, setProfile] = useState<EntityProfile | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<EntityProfile | null>(null);
  const [profileCache, setProfileCache] = useState<Record<number, EntityProfile>>({});
  const [loadingSelectedProfile, setLoadingSelectedProfile] = useState(false);
  const [selectedEnrichment, setSelectedEnrichment] = useState<EntityEnrichment | null>(null);
  const [enrichmentCache, setEnrichmentCache] = useState<Record<number, EntityEnrichment>>({});
  const [loadingEnrichment, setLoadingEnrichment] = useState(false);
  const [enhancingProfile, setEnhancingProfile] = useState(false);
  const [selectedRelationshipDetails, setSelectedRelationshipDetails] = useState<RelationshipDetail[] | null>(null);
  const [degreeCache, setDegreeCache] = useState<Record<number, DegreeCounts>>({});
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const [manualPositions, setManualPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [renderedNodes, setRenderedNodes] = useState<AppNode[]>([]);
  const [loadingSeed, setLoadingSeed] = useState(true);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<AppNode, AppEdge> | null>(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [exaSearchNotice, setExaSearchNotice] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    nodeId: string;
    entityId: number;
    label: string;
    x: number;
    y: number;
  } | null>(null);

  const profileRequestId = useRef(0);
  const enrichmentRequestIds = useRef<Set<number>>(new Set());
  const enrichmentCacheRef = useRef(enrichmentCache);
  const graphHasKeyboardFocus = useRef(false);
  enrichmentCacheRef.current = enrichmentCache;

  const expansionList = useMemo(() => Object.values(expansions), [expansions]);

  const toggleDirection = useCallback(
    async (originEntityId: number, direction: Direction, limit?: number) => {
      const key = expansionKey(originEntityId, direction);
      if (expansions[key]) {
        setExpansions((current) => {
          const next = { ...current };
          delete next[key];
          return next;
        });
        return;
      }

      setError(null);
      setLoadingExpansion({ entityId: originEntityId, direction });
      try {
        const requestedNodes = typeof limit === "number" ? Math.max(2, limit + 1) : 100;
        const data = await apiGet<NeighborhoodResponse>(
          `/entities/${originEntityId}/neighborhood?hops=1&include_inferred=true&direction=${direction}&max_nodes=${requestedNodes}`,
        );
        const directedEdges = data.edges.filter((edge) =>
          direction === "incoming" ? edge.target_entity_id === originEntityId : edge.source_entity_id === originEntityId,
        );
        const connectedIds = new Set<number>([originEntityId]);
        directedEdges.forEach((edge) => {
          connectedIds.add(edge.source_entity_id);
          connectedIds.add(edge.target_entity_id);
        });

        const inferred = (data.inferred_edges ?? []).map((edge) => ({ ...edge, seed_entity_id: originEntityId }));
        const inferredLimit =
          typeof limit === "number" ? Math.max(0, limit - Math.max(0, connectedIds.size - 1)) : 8;
        const inferredNodes =
          direction === "outgoing"
            ? inferred.slice(0, inferredLimit).map((edge) =>
                makeEntityNode(
                  {
                    id: edge.target_entity_id ?? Number(`9${edge.id}`),
                    name: edge.target_name,
                    type: edge.target_type,
                    state: null,
                    mention_count: 0,
                    depth: 1,
                  },
                  edge.verified ? "verified" : "inferred",
                ),
              )
            : [];

        const nodes = [
          ...data.nodes.filter((node) => connectedIds.has(node.id)).map((node) => makeEntityNode(node, "verified")),
          ...inferredNodes,
        ];
        const edges = [
          ...directedEdges.map(makeEdge),
          ...(direction === "outgoing"
            ? inferred.slice(0, inferredLimit).map((edge) => makeInferredEdge(edge, originEntityId))
            : []),
        ];
        const nodeIds = new Set(nodes.map((node) => node.id));
        const expansionEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
        const linkedNodeIds = edgeLinkedExpansionNodeIds(originEntityId, expansionEdges);
        const expansionNodes = nodes.filter((node) => linkedNodeIds.has(node.id));

        setExpansions((current) => ({
          ...current,
          [key]: {
            originEntityId,
            direction,
            nodes: expansionNodes,
            edges: expansionEdges,
            inferredEdges: inferred,
            nodeCount: countExpansionNeighbors(originEntityId, expansionEdges),
          },
        }));
      } catch (err) {
        setError(err instanceof Error ? err.message : `Could not load ${direction} graph`);
      } finally {
        setLoadingExpansion(null);
      }
    },
    [expansions],
  );

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoadingSeed(true);
    setBaseNode(null);
    setExpansions({});
    setManualPositions({});
    setSelectedNodeIds(new Set());
    setSelectedEntityId(entityId);
    setSelectedProfile(null);
    setLoadingSelectedProfile(true);
    profileRequestId.current += 1;

    apiGet<EntityProfile>(`/entities/${entityId}/profile`)
      .then((data) => {
        if (cancelled) return;
        setProfile(data);
        setSelectedProfile(data);
        setProfileCache((current) => ({
          ...current,
          [data.entity.id]: data,
        }));
        setDegreeCache((current) => ({
          ...current,
          [data.entity.id]: countsFromProfile(data),
        }));
        setBaseNode(
          makeEntityNode(
            {
              id: data.entity.id,
              name: data.entity.name,
              type: data.entity.type,
              state: data.entity.state,
              mention_count: data.entity.mention_count,
              depth: 0,
            },
            "verified",
          ),
        );
        setLoadingSeed(false);
        setLoadingSelectedProfile(false);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
          setLoadingSeed(false);
          setLoadingSelectedProfile(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  const graphNodes = useMemo(() => {
    const merged = mergeNodes([
      ...(baseNode ? [baseNode] : []),
      ...expansionList.flatMap((expansion) => expansion.nodes),
    ]);

    return merged.map((node) => {
      const entityIdForNode = node.data.entityId;
      const incoming = entityIdForNode ? expansions[expansionKey(entityIdForNode, "incoming")] : undefined;
      const outgoing = entityIdForNode ? expansions[expansionKey(entityIdForNode, "outgoing")] : undefined;
      const cachedCounts = degreeCache[entityIdForNode];

      return {
        ...node,
        selected: selectedNodeIds.has(node.id),
        data: {
          ...node.data,
          incomingLoaded: Boolean(incoming),
          outgoingLoaded: Boolean(outgoing),
          incomingCount: incoming?.nodeCount ?? cachedCounts?.incoming,
          outgoingCount: outgoing?.nodeCount ?? cachedCounts?.outgoing,
          loadingDirection:
            loadingExpansion?.entityId === entityIdForNode ? loadingExpansion.direction : null,
          onToggleDirection: toggleDirection,
        },
      };
    });
  }, [baseNode, degreeCache, expansionList, expansions, loadingExpansion, selectedNodeIds, toggleDirection]);

  const graphEdges = useMemo(() => mergeEdges(expansionList.flatMap((expansion) => expansion.edges)), [expansionList]);

  const visibleNodes = useMemo(() => {
    const normalizedSearch = searchText.trim().toLowerCase();

    return graphNodes.filter((node) => {
      if (!showInferred && node.data.status === "inferred") return false;

      if (normalizedSearch) {
        const haystack = `${node.data.label} ${node.data.subtitle} ${node.data.entityId}`.toLowerCase();
        if (!haystack.includes(normalizedSearch)) return false;
      }

      return true;
    });
  }, [graphNodes, searchText, showInferred]);

  const nodeLabelById = useMemo(
    () => new Map(graphNodes.map((node) => [node.id, node.data.label])),
    [graphNodes],
  );
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const exaRelationshipPairs = useMemo(
    () =>
      new Set(
        graphEdges
          .filter((edge) => edge.data?.status === "inferred")
          .map((edge) => `${edge.source}->${edge.target}`),
      ),
    [graphEdges],
  );

  const visibleEdges = useMemo(
    () =>
      graphEdges
        .filter((edge) => {
          if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) return false;
          return showInferred || edge.data?.status !== "inferred";
        })
        .map((edge) => {
          const amount = typeof edge.data?.amount === "number" ? edge.data.amount : null;
          const status = edge.data?.status ?? "verified";
          const isVerified = status === "verified";
          const hasExaRelationshipForPair = exaRelationshipPairs.has(`${edge.source}->${edge.target}`);
          const inferredEdges = edge.data?.inferredEdges ?? [];
          const sourceName = nodeLabelById.get(edge.source) ?? "This entity";
          const relationshipDetails = inferredEdges.map((inferredEdge) => ({
            edge: inferredEdge,
            summary: relationshipSummary(sourceName, inferredEdge.target_name, inferredEdge.relationship_type),
          }));
          return {
            ...edge,
            data: {
              ...edge.data,
              amount,
              status,
              relationshipDetails,
              onOpenDetails: relationshipDetails.length ? setSelectedRelationshipDetails : undefined,
            },
            label: showEdgeLabels && isVerified && !hasExaRelationshipForPair ? formatCompactMoney(amount) : undefined,
            labelBgPadding: [6, 3] as [number, number],
            labelBgBorderRadius: 4,
            labelBgStyle: { fill: "#f8fafc", fillOpacity: 0.92 },
            labelStyle: { fill: "#475569", fontSize: 11, fontWeight: 700 },
          };
        }),
    [exaRelationshipPairs, graphEdges, nodeLabelById, showEdgeLabels, showInferred, visibleNodeIds],
  );

  const layoutedNodes = useMemo(
    () => layoutGraph(visibleNodes, visibleEdges, expansionList),
    [expansionList, visibleEdges, visibleNodes],
  );
  const displayedNodes = useMemo(
    () =>
      layoutedNodes.map((node) => ({
        ...node,
        position: manualPositions[node.id] ?? node.position,
      })),
    [layoutedNodes, manualPositions],
  );
  useEffect(() => {
    setRenderedNodes(displayedNodes);
  }, [displayedNodes]);
  const viewportKey = useMemo(
    () => `${layoutedNodes.map((node) => node.id).join("|")}::${visibleEdges.map((edge) => edge.id).join("|")}`,
    [layoutedNodes, visibleEdges],
  );

  useEffect(() => {
    if (!flowInstance || layoutedNodes.length === 0) return;
    const timeout = window.setTimeout(() => {
      flowInstance.fitView({ padding: 0.22, duration: 450, includeHiddenNodes: false });
    }, 80);

    return () => window.clearTimeout(timeout);
  }, [flowInstance, layoutedNodes.length, viewportKey]);

  const inferredRows = useMemo(() => {
    const seen = new Set<number>();
    return expansionList.flatMap((expansion) => expansion.inferredEdges).filter((edge) => {
      if (seen.has(edge.id)) return false;
      seen.add(edge.id);
      return true;
    });
  }, [expansionList]);
  const displayProfile = selectedProfile ?? profile;
  const detailProfile = selectedProfile;
  const selectedNodeSummary = useMemo(
    () => graphNodes.find((node) => node.data.entityId === selectedEntityId)?.data,
    [graphNodes, selectedEntityId],
  );
  const isSelectedExaOnly = selectedNodeSummary?.status === "inferred";
  const sidebarTitle = selectedNodeSummary?.label ?? displayProfile?.entity.name ?? "Loading entity";
  const sidebarSubtitle =
    [titleize(detailProfile?.entity.type), titleize(detailProfile?.entity.state)].filter(Boolean).join(" · ") ||
    selectedNodeSummary?.subtitle ||
    "Unknown";
  const loadingMessage = loadingSeed
    ? `Loading entity #${entityId}`
    : loadingExpansion
      ? `Loading ${loadingExpansion.direction} graph`
      : searchingExa
        ? "Searching Exa"
        : null;

  const incomingRows = useMemo(
    () =>
      (detailProfile?.finance.recent_edges ?? [])
        .filter((edge) => edge.direction === "incoming")
        .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0)),
    [detailProfile],
  );

  const outgoingRows = useMemo(
    () =>
      (detailProfile?.finance.recent_edges ?? [])
        .filter((edge) => edge.direction === "outgoing")
        .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0)),
    [detailProfile],
  );

  const selectedInferredRows = useMemo(() => {
    if (!selectedEntityId) return [];
    return inferredRows.filter((edge) => edge.seed_entity_id === selectedEntityId || edge.target_entity_id === selectedEntityId);
  }, [inferredRows, selectedEntityId]);

  const selectedInferredDetails = useMemo(() => {
    const entityNames = new Map(graphNodes.map((node) => [node.data.entityId, node.data.label]));
    return selectedInferredRows.map((edge) => {
      const sourceName = edge.seed_entity_id ? entityNames.get(edge.seed_entity_id) : null;
      return {
        edge,
        summary: relationshipSummary(sourceName ?? "This entity", edge.target_name, edge.relationship_type),
      };
    });
  }, [graphNodes, selectedInferredRows]);

  useEffect(() => {
    if (!showInferred || !selectedEntityId) {
      setSelectedEnrichment(null);
      setLoadingEnrichment(false);
      setEnhancingProfile(false);
      return;
    }

    const cachedEnrichment = enrichmentCacheRef.current[selectedEntityId];
    if (cachedEnrichment) {
      setSelectedEnrichment(cachedEnrichment);
      setLoadingEnrichment(false);
      setEnhancingProfile(false);
      return;
    }

    let cancelled = false;
    const entityIdToEnrich = selectedEntityId;

    async function loadEnrichment() {
      setSelectedEnrichment(null);
      setLoadingEnrichment(true);
      setEnhancingProfile(false);
      try {
        const storedEnrichment = await apiGetOptional<EntityEnrichment>(`/entities/${entityIdToEnrich}/enrichment`);
        if (cancelled) return;

        if (storedEnrichment) {
          setSelectedEnrichment(storedEnrichment);
          setEnrichmentCache((current) => ({
            ...current,
            [entityIdToEnrich]: storedEnrichment,
          }));
          return;
        }

        if (enrichmentRequestIds.current.has(entityIdToEnrich)) return;
        enrichmentRequestIds.current.add(entityIdToEnrich);
        setLoadingEnrichment(false);
        setEnhancingProfile(true);

        const newEnrichment = await apiPost<EntityEnrichment>(`/entities/${entityIdToEnrich}/enrich`, {});
        if (cancelled) return;

        setSelectedEnrichment(newEnrichment);
        setEnrichmentCache((current) => ({
          ...current,
          [entityIdToEnrich]: newEnrichment,
        }));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load Exa enrichment");
      } finally {
        enrichmentRequestIds.current.delete(entityIdToEnrich);
        if (!cancelled) {
          setLoadingEnrichment(false);
          setEnhancingProfile(false);
        }
      }
    }

    void loadEnrichment();

    return () => {
      cancelled = true;
    };
  }, [selectedEntityId, showInferred]);

  async function onNodeClick(event: React.MouseEvent, node: AppNode) {
    setContextMenu(null);
    const data = node.data;
    const requestId = profileRequestId.current + 1;
    profileRequestId.current = requestId;
    setSelectedNodeIds((current) => {
      if (event.metaKey || event.ctrlKey) {
        const next = new Set(current);
        if (next.has(node.id)) next.delete(node.id);
        else next.add(node.id);
        return next;
      }

      return new Set([node.id]);
    });
    setSelectedEntityId(data.entityId);

    if (data.status === "inferred") {
      setSelectedProfile(null);
      setLoadingSelectedProfile(false);
      setError(null);
      return;
    }

    const cachedProfile = profileCache[data.entityId];
    if (cachedProfile) {
      setSelectedProfile(cachedProfile);
      setLoadingSelectedProfile(false);
      setError(null);
      return;
    }

    setSelectedProfile(null);
    setLoadingSelectedProfile(true);
    setError(null);
    try {
      const nextProfile = await apiGet<EntityProfile>(`/entities/${data.entityId}/profile`);
      if (profileRequestId.current !== requestId) return;
      setSelectedProfile(nextProfile);
      setProfileCache((current) => ({
        ...current,
        [nextProfile.entity.id]: nextProfile,
      }));
      setLoadingSelectedProfile(false);
      setDegreeCache((current) => ({
        ...current,
        [nextProfile.entity.id]: countsFromProfile(nextProfile),
      }));
    } catch (err) {
      if (profileRequestId.current !== requestId) return;
      setLoadingSelectedProfile(false);
      setError(err instanceof Error ? err.message : "Could not load profile");
    }
  }

  const focusOnNode = useCallback(
    (nodeId: string) => {
      const keepNodeIds = new Set<string>([nodeId]);

      graphEdges.forEach((edge) => {
        if (edge.source === nodeId) keepNodeIds.add(edge.target);
        if (edge.target === nodeId) keepNodeIds.add(edge.source);
      });

      setBaseNode((currentBase) => {
        if (!currentBase || !keepNodeIds.has(currentBase.id)) return null;
        return currentBase;
      });

      setExpansions((current) => {
        const next: Record<string, ExpansionRecord> = {};

        Object.entries(current).forEach(([key, expansion]) => {
          const originNodeId = entityNodeId(expansion.originEntityId);
          if (!keepNodeIds.has(originNodeId)) return;

          const nodes = expansion.nodes.filter((node) => keepNodeIds.has(node.id));
          const edges = expansion.edges.filter((edge) => keepNodeIds.has(edge.source) && keepNodeIds.has(edge.target));
          if (nodes.length === 0) return;

          const inferredEdges = expansion.inferredEdges.filter((edge) => {
            const targetId = edge.target_entity_id == null ? `entity-9${edge.id}` : entityNodeId(edge.target_entity_id);
            return keepNodeIds.has(targetId);
          });

          next[key] = {
            ...expansion,
            nodes,
            edges,
            inferredEdges,
            nodeCount: countExpansionNeighbors(expansion.originEntityId, edges),
          };
        });

        return next;
      });

      setSelectedNodeIds(new Set([nodeId]));
      setContextMenu(null);
    },
    [graphEdges],
  );

  function onNodeContextMenu(event: React.MouseEvent, node: AppNode) {
    event.preventDefault();
    event.stopPropagation();
    setSelectedNodeIds(new Set([node.id]));
    setContextMenu({
      nodeId: node.id,
      entityId: node.data.entityId,
      label: node.data.label,
      x: event.clientX,
      y: event.clientY,
    });
  }

  const deleteSelectedNodes = useCallback(() => {
    if (selectedNodeIds.size === 0) return;

    setBaseNode((currentBase) => {
      if (!currentBase || !selectedNodeIds.has(currentBase.id)) return currentBase;
      return null;
    });

    setExpansions((current) => {
      const next: Record<string, ExpansionRecord> = {};

      Object.entries(current).forEach(([key, expansion]) => {
        const originNodeId = entityNodeId(expansion.originEntityId);
        if (selectedNodeIds.has(originNodeId)) return;

        const nodes = expansion.nodes.filter((node) => !selectedNodeIds.has(node.id));
        const edges = expansion.edges.filter(
          (edge) => !selectedNodeIds.has(edge.source) && !selectedNodeIds.has(edge.target),
        );
        const inferredEdges = expansion.inferredEdges.filter((edge) => {
          const targetId = edge.target_entity_id == null ? `entity-9${edge.id}` : entityNodeId(edge.target_entity_id);
          return !selectedNodeIds.has(targetId);
        });

        next[key] = {
          ...expansion,
          nodes,
          edges,
          inferredEdges,
          nodeCount: countExpansionNeighbors(expansion.originEntityId, edges),
        };
      });

      return next;
    });

    if (selectedEntityId && selectedNodeIds.has(entityNodeId(selectedEntityId))) {
        setSelectedEntityId(null);
        setSelectedProfile(null);
        setLoadingSelectedProfile(false);
    }

    setManualPositions((current) => {
      const next = { ...current };
      selectedNodeIds.forEach((nodeId) => delete next[nodeId]);
      return next;
    });
    setSelectedNodeIds(new Set());
  }, [selectedEntityId, selectedNodeIds]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();
      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;

      if (event.key === "Escape") {
        setContextMenu(null);
        return;
      }

      if (event.metaKey && event.key.toLowerCase() === "a" && graphHasKeyboardFocus.current) {
        event.preventDefault();
        setSelectedNodeIds(new Set(visibleNodes.map((node) => node.id)));
        setContextMenu(null);
        return;
      }

      if (event.key !== "Delete" && event.key !== "Backspace") return;

      event.preventDefault();
      deleteSelectedNodes();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteSelectedNodes, visibleNodes]);

  async function searchExaForNode(entityIdToSearch: number, entityName: string, depth: number) {
    if (!showInferred) return;
    const existingInferredIds = new Set(
      inferredRows.filter((edge) => edge.seed_entity_id === entityIdToSearch).map((edge) => edge.id),
    );
    setSearchingExa(true);
    setContextMenu(null);
    setError(null);
    setExaSearchNotice(null);
    try {
      const clampedDepth = Math.max(1, Math.min(depth, 5));
      await apiPost("/discover", { entity_name: entityName, depth: clampedDepth, max_expand: 3 });
      const data = await apiGet<InferredResponse>(`/entities/${entityIdToSearch}/inferred`);
      const inferred = data.inferred_edges.map((edge) => ({ ...edge, seed_entity_id: entityIdToSearch }));
      const newInferredCount = inferred.filter((edge) => !existingInferredIds.has(edge.id)).length;
      if (inferred.length === 0) {
        setExaSearchNotice(`No Exa discoveries found for ${entityName}.`);
        return;
      }
      if (newInferredCount === 0) {
        setExaSearchNotice(`No new Exa discoveries found for ${entityName}.`);
      }
      const nodes = inferred.slice(0, 10).map((edge) =>
        makeEntityNode(
          {
            id: edge.target_entity_id ?? Number(`9${edge.id}`),
            name: edge.target_name,
            type: edge.target_type,
            state: null,
            mention_count: 0,
            depth: 1,
          },
          edge.verified ? "verified" : "inferred",
        ),
      );
      const originProfile = profileCache[entityIdToSearch];
      const originNode = graphNodes.find((node) => node.data.entityId === entityIdToSearch);
      const edges = inferred.map((edge) => makeInferredEdge(edge, entityIdToSearch));
      const nodeIds = new Set([entityNodeId(entityIdToSearch), ...nodes.map((node) => node.id)]);
      const expansionEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
      setExpansions((current) => ({
        ...current,
        [`${entityIdToSearch}:exa`]: {
          originEntityId: entityIdToSearch,
          direction: "outgoing",
          nodes: [
            makeEntityNode(
              {
                id: entityIdToSearch,
                name: originProfile?.entity.name ?? originNode?.data.label ?? entityName,
                type: originProfile?.entity.type ?? null,
                state: originProfile?.entity.state ?? null,
                mention_count: originProfile?.entity.mention_count ?? 0,
                depth: 0,
              },
              "verified",
            ),
            ...nodes,
          ],
          edges: expansionEdges,
          inferredEdges: inferred,
          nodeCount: countExpansionNeighbors(entityIdToSearch, expansionEdges),
        },
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search Exa failed");
      setExaSearchNotice(null);
    } finally {
      setSearchingExa(false);
    }
  }

  return (
    <div className="ig-shell">
      <Sidebar
        title={sidebarTitle}
        subtitle={sidebarSubtitle}
        error={error}
        loadingSeed={loadingSeed}
        loadingProfile={loadingSelectedProfile}
        hasNodes={graphNodes.length > 0}
        isExaOnly={Boolean(isSelectedExaOnly)}
        incomingTotal={detailProfile?.finance.incoming_total}
        outgoingTotal={detailProfile?.finance.outgoing_total}
        incomingRows={incomingRows}
        outgoingRows={outgoingRows}
        showInferred={showInferred}
        enrichment={selectedEnrichment}
        loadingEnrichment={loadingEnrichment}
        enhancingProfile={enhancingProfile}
        relationshipDetails={selectedInferredDetails}
        onPointerDown={() => {
          graphHasKeyboardFocus.current = false;
        }}
      />

      <main
        className="ig-main"
        onPointerDown={() => {
          graphHasKeyboardFocus.current = true;
        }}
      >
        <GraphToolbar
          showInferred={showInferred}
          showEdgeLabels={showEdgeLabels}
          searchText={searchText}
          onToggleInferred={() => setShowInferred((value) => !value)}
          onToggleEdgeLabels={() => setShowEdgeLabels((value) => !value)}
          onSearchTextChange={setSearchText}
        />
        {loadingMessage && <GraphLoadingOverlay message={loadingMessage} />}
        {exaSearchNotice && !loadingMessage && (
          <ExaSearchNotice message={exaSearchNotice} onDismiss={() => setExaSearchNotice(null)} />
        )}
        {!loadingMessage && graphNodes.length > 0 && visibleNodes.length === 0 && (
          <GraphEmptyOverlay message="No loaded nodes match the current filters." />
        )}
        <ReactFlow
          nodes={renderedNodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={(changes: NodeChange<AppNode>[]) => {
            setRenderedNodes((current) => applyNodeChanges(changes, current) as AppNode[]);
          }}
          onNodeClick={onNodeClick}
          onNodeContextMenu={onNodeContextMenu}
          onNodeDragStop={(_, node) => {
            setManualPositions((current) => ({
              ...current,
              [node.id]: node.position,
            }));
          }}
          onPaneClick={() => {
            setSelectedNodeIds(new Set());
            setContextMenu(null);
          }}
          onInit={setFlowInstance}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.28}
          maxZoom={1.4}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#cbd5e1" gap={24} />
          <Controls />
        </ReactFlow>
        <GraphLegend onRearrange={() => setManualPositions({})} />
        {contextMenu && (
          <NodeContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            exaEnabled={showInferred}
            searchingExa={searchingExa}
            onFocus={() => focusOnNode(contextMenu.nodeId)}
            onSearchExa={(depth) => void searchExaForNode(contextMenu.entityId, contextMenu.label, depth)}
            onClose={() => setContextMenu(null)}
          />
        )}
        {selectedRelationshipDetails && (
          <RelationshipDetailsModal
            edges={selectedRelationshipDetails}
            onClose={() => setSelectedRelationshipDetails(null)}
          />
        )}
      </main>
    </div>
  );
}
