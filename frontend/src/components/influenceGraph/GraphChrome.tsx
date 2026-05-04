import { useState } from "react";
import { createPortal } from "react-dom";
import type { RelationshipDetail } from "./types";

export function GraphToolbar({
  showInferred,
  showEdgeLabels,
  searchText,
  onToggleInferred,
  onToggleEdgeLabels,
  onSearchTextChange,
}: {
  showInferred: boolean;
  showEdgeLabels: boolean;
  searchText: string;
  onToggleInferred: () => void;
  onToggleEdgeLabels: () => void;
  onSearchTextChange: (value: string) => void;
}) {
  return (
    <div className="ig-toolbar">
      <div className="ig-toolbar-row">
        <ToggleControl label="Exa" enabled={showInferred} onToggle={onToggleInferred} />
        <ToggleControl
          label="Dollar labels"
          enabled={showEdgeLabels}
          onToggle={onToggleEdgeLabels}
          enabledClassName="bg-slate-900"
        />
      </div>
      <input
        type="text"
        value={searchText}
        onChange={(event) => onSearchTextChange(event.target.value)}
        placeholder="Search loaded nodes"
        className="ig-search-input"
      />
    </div>
  );
}

export function ToggleControl({
  label,
  enabled,
  onToggle,
  enabledClassName = "bg-emerald-500",
}: {
  label: string;
  enabled: boolean;
  onToggle: () => void;
  enabledClassName?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span>{label}</span>
      <button
        type="button"
        onClick={onToggle}
        className={`h-6 w-11 rounded-full p-1 transition ${enabled ? enabledClassName : "bg-slate-300"}`}
      >
        <span className={`block h-4 w-4 rounded-full bg-white transition ${enabled ? "translate-x-5" : ""}`} />
      </button>
    </div>
  );
}

export function ExaSearchNotice({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="absolute left-1/2 top-4 z-20 max-w-md -translate-x-1/2 rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-950 shadow-sm">
      <div className="flex items-center gap-3">
        <span className="min-w-0">{message}</span>
        <button
          type="button"
          className="shrink-0 rounded px-1.5 py-0.5 text-xs font-bold text-amber-700 hover:bg-amber-100"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function GraphLoadingOverlay({ message }: { message: string }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-4 z-10 flex justify-center">
      <div className="flex items-center gap-3 rounded-md border border-slate-200 bg-white/95 px-4 py-2 text-sm font-medium text-slate-700 shadow-sm">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
        {message}
      </div>
    </div>
  );
}

export function GraphEmptyOverlay({ message }: { message: string }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <div className="rounded-md border border-slate-200 bg-white/95 px-4 py-3 text-sm font-medium text-slate-600 shadow-sm">
        {message}
      </div>
    </div>
  );
}

export function GraphLegend({ onRearrange }: { onRearrange: () => void }) {
  return (
    <div className="absolute bottom-4 left-4 z-10 rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-700 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="font-semibold text-slate-900">Legend</div>
        <button
          type="button"
          className="rounded border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-600 hover:border-slate-300 hover:text-slate-950"
          onClick={onRearrange}
        >
          Rearrange
        </button>
      </div>
      <div className="grid gap-1.5">
        <div className="flex items-center gap-2">
          <span className="h-3 w-5 rounded-sm border border-slate-300 bg-white" />
          <span>Campaign disclosure entity</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-5 rounded-sm border border-amber-300 bg-amber-50" />
          <span>Exa-discovered entity</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-0 w-5 border-t-2 border-slate-500" />
          <span>Campaign disclosure</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-0 w-5 border-t-2 border-dashed border-amber-600" />
          <span>Exa discovery</span>
        </div>
      </div>
    </div>
  );
}

export function RelationshipDetailsModal({ edges, onClose }: { edges: RelationshipDetail[]; onClose: () => void }) {
  const title = edges.length === 1 ? edges[0].edge.target_name : `${edges.length} Exa discoveries`;
  return createPortal(
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-slate-950/35 px-4" onClick={onClose}>
      <div
        className="max-h-[82vh] w-full max-w-xl overflow-hidden rounded-md border border-slate-200 bg-white text-slate-950 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-amber-700">Exa evidence</div>
            <h2 className="mt-1 truncate text-lg font-semibold">{title}</h2>
          </div>
          <button
            type="button"
            className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="max-h-[64vh] overflow-y-auto px-5 py-4">
          <div className="space-y-3">
            {edges.map(({ edge, summary }) => (
              <article key={edge.id} className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold leading-snug text-slate-950">{summary}</span>
                  <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.08em] text-amber-800">
                    {edge.evidence_strength ?? "unknown"}
                  </span>
                </div>

                {edge.evidence_quotes.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {edge.evidence_quotes.slice(0, 3).map((quote, index) => (
                      <blockquote
                        key={`${edge.id}-${index}-${quote}`}
                        className="rounded-md border border-slate-200 bg-white px-3 py-2 leading-relaxed text-slate-700"
                        title={quote}
                      >
                        {quote}
                      </blockquote>
                    ))}
                  </div>
                )}

                {edge.source_urls.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {edge.source_urls.slice(0, 4).map((url, index) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:border-amber-300 hover:text-amber-800"
                      >
                        {edge.source_domains[index] || "Source"}
                      </a>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function NodeContextMenu({
  x,
  y,
  exaEnabled,
  searchingExa,
  onFocus,
  onSearchExa,
  onClose,
}: {
  x: number;
  y: number;
  exaEnabled: boolean;
  searchingExa: boolean;
  onFocus: () => void;
  onSearchExa: (depth: number) => void;
  onClose: () => void;
}) {
  const [showSearchDepth, setShowSearchDepth] = useState(false);
  const [depth, setDepth] = useState("1");
  const parsedDepth = Math.max(1, Math.min(Number(depth) || 1, 5));

  return (
    <div
      className="fixed z-50 w-56 overflow-hidden rounded-md border border-slate-200 bg-white text-sm shadow-lg"
      style={{ left: x, top: y }}
      onContextMenu={(event) => event.preventDefault()}
    >
      <button
        type="button"
        className="block w-full px-3 py-2 text-left font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-950"
        onClick={onFocus}
      >
        Focus on this node only
      </button>
      {exaEnabled && (
        showSearchDepth ? (
          <div className="border-t border-slate-100 px-3 py-2">
            <label className="block">
              <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">Exa depth</span>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={depth}
                onChange={(event) => setDepth(event.target.value.replace(/\D/g, ""))}
                onKeyDown={(event) => {
                  event.stopPropagation();
                  if (event.key === "Enter") onSearchExa(parsedDepth);
                  if (event.key === "Escape") setShowSearchDepth(false);
                }}
                className="mt-1 h-8 w-full rounded border border-slate-300 bg-white px-2 text-sm text-slate-950 outline-none focus:border-slate-500"
              />
            </label>
            <button
              type="button"
              disabled={searchingExa}
              className="mt-2 w-full rounded bg-slate-900 px-2 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:cursor-wait disabled:opacity-50"
              onClick={() => onSearchExa(parsedDepth)}
            >
              {searchingExa ? "Searching..." : `Search depth ${parsedDepth}`}
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="block w-full border-t border-slate-100 px-3 py-2 text-left font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-950"
            onClick={() => setShowSearchDepth(true)}
          >
            Expand graph with Exa
          </button>
        )
      )}
      <button type="button" className="block w-full px-3 py-2 text-left text-slate-500 hover:bg-slate-50" onClick={onClose}>
        Cancel
      </button>
    </div>
  );
}
