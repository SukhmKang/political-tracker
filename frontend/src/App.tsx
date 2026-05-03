import { useEffect, useMemo, useRef, useState } from "react";
import InfluenceGraph from "./components/InfluenceGraph";

const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

interface EntitySearchResult {
  id: number;
  name: string | null;
  type: string | null;
  state: string | null;
  state_code: string | null;
  mention_count: number;
}

function readInitialEntityId(): number | null {
  const value = new URLSearchParams(window.location.search).get("entityId");
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export default function App() {
  const [entityId, setEntityId] = useState<number | null>(() => readInitialEntityId());
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<EntitySearchResult[]>([]);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchRef = useRef<HTMLDivElement | null>(null);
  const selectedQueryRef = useRef<string | null>(null);

  const trimmedQuery = useMemo(() => query.trim(), [query]);

  useEffect(() => {
    if (trimmedQuery.length < 2) {
      setResults([]);
      setLoadingSearch(false);
      setSearchError(null);
      return;
    }

    if (selectedQueryRef.current === trimmedQuery) {
      setResults([]);
      setLoadingSearch(false);
      setSearchError(null);
      setSearchOpen(false);
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoadingSearch(true);
      setSearchError(null);
      fetch(`${API_BASE}/entities/search?q=${encodeURIComponent(trimmedQuery)}&limit=8`, {
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error(`Search failed (${response.status})`);
          return response.json() as Promise<EntitySearchResult[]>;
        })
        .then((data) => {
          setResults(data);
          setSearchOpen(true);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setSearchError(err instanceof Error ? err.message : "Search failed");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoadingSearch(false);
        });
    }, 180);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [trimmedQuery]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || searchRef.current?.contains(target)) return;
      setSearchOpen(false);
    }

    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, []);

  function selectEntity(result: EntitySearchResult) {
    const label = result.name ?? `Entity ${result.id}`;
    selectedQueryRef.current = label.trim();
    setEntityId(result.id);
    setQuery(label);
    setSearchOpen(false);
    setResults([]);
    window.history.replaceState(null, "", `?entityId=${result.id}`);
  }

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-slate-100 text-slate-950">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5">
        <div>
          <div className="text-sm font-semibold text-slate-950">State Political Tracker</div>
          <div className="text-xs text-slate-500">Influence graph demo</div>
        </div>
        <div ref={searchRef} className="relative w-80">
          <label className="sr-only" htmlFor="entity-search">
            Search entity
          </label>
          <input
            id="entity-search"
            type="text"
            value={query}
            placeholder="Search entities by name"
            autoComplete="off"
            onChange={(event) => {
              selectedQueryRef.current = null;
              setQuery(event.target.value);
              setSearchOpen(true);
            }}
            onFocus={() => {
              if (selectedQueryRef.current !== trimmedQuery) setSearchOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && results[0]) selectEntity(results[0]);
              if (event.key === "Escape") setSearchOpen(false);
            }}
            className="h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 outline-none focus:border-slate-500"
          />
          {searchOpen && trimmedQuery.length >= 2 && (
            <div className="absolute right-0 top-11 z-50 max-h-80 w-full overflow-y-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-xl">
              {loadingSearch ? (
                <div className="px-3 py-2 text-slate-500">Searching...</div>
              ) : searchError ? (
                <div className="px-3 py-2 text-red-600">{searchError}</div>
              ) : results.length ? (
                results.map((result) => (
                  <button
                    key={result.id}
                    type="button"
                    className="block w-full px-3 py-2 text-left hover:bg-slate-50"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectEntity(result)}
                  >
                    <div className="truncate font-semibold text-slate-950">{result.name ?? `Entity ${result.id}`}</div>
                    <div className="mt-0.5 truncate text-xs text-slate-500">
                      {[result.state, result.type].filter(Boolean).join(" · ") || "Unknown"}
                    </div>
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-slate-500">No matching entities.</div>
              )}
            </div>
          )}
        </div>
      </header>
      <div className="min-h-0 flex-1">
        {entityId ? <InfluenceGraph entityId={entityId} /> : <EmptyStartState />}
      </div>
    </div>
  );
}

function EmptyStartState() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-slate-100">
      <div className="max-w-md rounded-md border border-slate-200 bg-white px-6 py-5 text-center shadow-sm">
        <div className="text-base font-semibold text-slate-950">Choose a starting entity</div>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Use the search box in the top-right corner to find an entity by name, then select one to load the graph.
        </p>
      </div>
    </div>
  );
}
