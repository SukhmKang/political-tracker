import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  getBezierPath,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import type { AppEdge, Direction, EntityNodeData } from "./types";
import { EXPANSION_LIMIT_THRESHOLD } from "./model";
import { titleize, truncate } from "./format";

function EntityNode({ data, selected }: NodeProps<Node<EntityNodeData>>) {
  const nodeClass = `ig-node ig-node--${data.status}${selected ? " ig-node--selected" : ""}`;

  return (
    <div className={nodeClass}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-slate-400 !opacity-45" />
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-slate-400 !opacity-45" />
      <NodeArrow
        direction="incoming"
        entityId={data.entityId}
        loaded={Boolean(data.incomingLoaded)}
        count={typeof data.incomingCount === "number" ? data.incomingCount : undefined}
        loading={data.loadingDirection === "incoming"}
        onToggle={data.onToggleDirection}
      />
      <NodeArrow
        direction="outgoing"
        entityId={data.entityId}
        loaded={Boolean(data.outgoingLoaded)}
        count={typeof data.outgoingCount === "number" ? data.outgoingCount : undefined}
        loading={data.loadingDirection === "outgoing"}
        onToggle={data.onToggleDirection}
      />
      <div className="ig-node-status">{titleize(data.status)}</div>
      <div className="ig-node-title">{truncate(data.label, 24)}</div>
      <div className="ig-node-subtitle">{data.subtitle || "Entity"}</div>
    </div>
  );
}

function NodeArrow({
  direction,
  entityId,
  loaded,
  count,
  loading,
  onToggle,
}: {
  direction: Direction;
  entityId: number;
  loaded: boolean;
  count?: number;
  loading: boolean;
  onToggle?: (entityId: number, direction: Direction, limit?: number) => void;
}) {
  const [showLimitInput, setShowLimitInput] = useState(false);
  const [limitValue, setLimitValue] = useState("");
  const [popupPosition, setPopupPosition] = useState<{ x: number; y: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const isIncoming = direction === "incoming";
  const label = isIncoming ? "incoming" : "outgoing";
  const countLabel = typeof count === "number" ? `${count} ${count === 1 ? "node" : "nodes"}` : "count unknown";
  const title = loaded ? `Collapse ${label} expansion (${countLabel})` : `Load ${label} edges (${countLabel})`;
  const isEmpty = loaded && count === 0;
  const shouldAskForLimit = !loaded && typeof count === "number" && count > EXPANSION_LIMIT_THRESHOLD;
  const sanitizedLimitValue = limitValue.replace(/\D/g, "");
  const parsedLimit = Math.max(1, Math.min(Number(sanitizedLimitValue) || Math.min(count ?? 25, 25), count ?? 500));
  const arrowClass = [
    "ig-node-arrow",
    isIncoming ? "ig-node-arrow--incoming" : "ig-node-arrow--outgoing",
    loaded ? "ig-node-arrow--loaded" : "",
    isEmpty ? "ig-node-arrow--empty" : "",
  ]
    .filter(Boolean)
    .join(" ");

  function toggleWithOptionalLimit(event: React.MouseEvent) {
    event.stopPropagation();

    if (loaded || !shouldAskForLimit) {
      setShowLimitInput(false);
      onToggle?.(entityId, direction);
      return;
    }

    setLimitValue((current) => current || String(Math.min(count, 25)));
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) {
      setPopupPosition({
        x: isIncoming ? rect.left : rect.right - 128,
        y: rect.bottom + 8,
      });
    }
    setShowLimitInput((current) => !current);
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        title={title}
        aria-label={title}
        onClick={toggleWithOptionalLimit}
        disabled={loading}
        className={arrowClass}
      >
        <span>{loading ? "..." : isIncoming ? "←" : "→"}</span>
        {typeof count === "number" && (
          <span className={`ig-node-arrow-count${isEmpty ? " ig-node-arrow-count--empty" : ""}`}>{count}</span>
        )}
      </button>
      {showLimitInput && (
        <NodeLimitPopup
          x={popupPosition?.x ?? 0}
          y={popupPosition?.y ?? 0}
          value={limitValue}
          parsedLimit={parsedLimit}
          onChange={setLimitValue}
          onSubmit={() => {
            setShowLimitInput(false);
            onToggle?.(entityId, direction, parsedLimit);
          }}
          onClose={() => setShowLimitInput(false)}
        />
      )}
    </>
  );
}

function NodeLimitPopup({
  x,
  y,
  value,
  parsedLimit,
  onChange,
  onSubmit,
  onClose,
}: {
  x: number;
  y: number;
  value: string;
  parsedLimit: number;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}) {
  return createPortal(
    <div
      className="fixed z-[9999] w-32 rounded-md border border-slate-200 bg-white p-2 text-left text-slate-950 shadow-xl"
      style={{ left: x, top: y }}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <label className="block text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">Nodes</label>
      <input
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        value={value}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, ""))}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Enter") onSubmit();
          if (event.key === "Escape") onClose();
        }}
        className="mt-1 h-7 w-full rounded border border-slate-300 bg-white px-2 text-sm text-slate-950 outline-none focus:border-slate-500"
      />
      <button
        type="button"
        className="mt-2 w-full rounded bg-slate-900 px-2 py-1.5 text-xs font-semibold text-white hover:bg-slate-700"
        onClick={(event) => {
          event.stopPropagation();
          onSubmit();
        }}
      >
        Expand {parsedLimit}
      </button>
    </div>,
    document.body,
  );
}

function ExaRelationshipEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  data,
}: EdgeProps<AppEdge>) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const relationshipDetails = data?.relationshipDetails ?? [];

  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <button
          type="button"
          title="View Exa relationship details"
          className="nodrag nopan ig-exa-edge-pill"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: "all",
          }}
          onClick={(event) => {
            event.stopPropagation();
            if (relationshipDetails.length) data?.onOpenDetails?.(relationshipDetails);
          }}
        >
          Details
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

export const nodeTypes = {
  entity: EntityNode,
};

export const edgeTypes = {
  exaRelationship: ExaRelationshipEdge,
};
