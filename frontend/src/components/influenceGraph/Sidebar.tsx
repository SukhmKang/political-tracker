import type { EntityEnrichment, RecentEdge, RelationshipDetail } from "./types";
import { formatDate, formatMoney, formatMoneyOrDash, titleize } from "./format";

interface SidebarProps {
  title: string;
  subtitle: string;
  error: string | null;
  loadingSeed: boolean;
  loadingProfile: boolean;
  hasNodes: boolean;
  isExaOnly: boolean;
  incomingTotal?: number | null;
  outgoingTotal?: number | null;
  incomingRows: RecentEdge[];
  outgoingRows: RecentEdge[];
  showInferred: boolean;
  enrichment: EntityEnrichment | null;
  loadingEnrichment: boolean;
  enhancingProfile: boolean;
  relationshipDetails: RelationshipDetail[];
  onPointerDown: () => void;
}

export function Sidebar({
  title,
  subtitle,
  error,
  loadingSeed,
  loadingProfile,
  hasNodes,
  isExaOnly,
  incomingTotal,
  outgoingTotal,
  incomingRows,
  outgoingRows,
  showInferred,
  enrichment,
  loadingEnrichment,
  enhancingProfile,
  relationshipDetails,
  onPointerDown,
}: SidebarProps) {
  return (
    <aside className="ig-sidebar" onPointerDown={onPointerDown}>
      <div className="ig-sidebar-header">
        {loadingSeed ? (
          <div className="h-6 w-56 animate-pulse rounded bg-slate-200" />
        ) : !hasNodes ? (
          <div className="h-6" />
        ) : (
          <div>
            <h1 className="truncate text-lg font-semibold">{title}</h1>
            <div className="mt-1 truncate text-sm text-slate-500">{loadingProfile ? "-" : subtitle}</div>
          </div>
        )}
        {error && <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      </div>

      <div className="ig-sidebar-body">
        {!hasNodes && !loadingSeed ? null : loadingSeed ? (
          <SidebarSkeleton />
        ) : !isExaOnly ? (
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <InfoItem label="Incoming $" value={formatMoneyOrDash(incomingTotal)} />
            <InfoItem label="Outgoing $" value={formatMoneyOrDash(outgoingTotal)} />
          </dl>
        ) : null}

        {loadingProfile && !loadingSeed && <ProfileLoadingNotice entityName={title} />}

        {showInferred && (enrichment || loadingEnrichment || enhancingProfile) && (
          <ExaEnrichmentPanel enrichment={enrichment} loading={loadingEnrichment} enhancing={enhancingProfile} />
        )}

        {!isExaOnly && (
          <>
            <EdgeTable title="Incoming" edges={incomingRows} loading={loadingProfile} />
            <EdgeTable title="Outgoing" edges={outgoingRows} loading={loadingProfile} />
          </>
        )}
        {relationshipDetails.length > 0 && <InferredTable details={relationshipDetails} />}
      </div>
    </aside>
  );
}

function SidebarSkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="h-3 w-14 animate-pulse rounded bg-slate-200" />
            <div className="mt-2 h-4 w-20 animate-pulse rounded bg-slate-200" />
          </div>
        ))}
      </div>
      <div className="h-9 animate-pulse rounded-md bg-slate-200" />
      <div className="space-y-2">
        <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
        <div className="h-28 animate-pulse rounded-md bg-slate-100" />
      </div>
    </div>
  );
}

function InfoItem({ label, value, loading = false }: { label: string; value?: string | number | null; loading?: boolean }) {
  return (
    <div className="ig-panel-card px-3 py-2">
      <dt className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-slate-900">{loading ? "-" : value || "Unknown"}</dd>
    </div>
  );
}

function ExaEnrichmentPanel({
  enrichment,
  loading,
  enhancing,
}: {
  enrichment: EntityEnrichment | null;
  loading: boolean;
  enhancing: boolean;
}) {
  const hasDisplayValue = (value: unknown) => {
    if (value == null) return false;
    if (typeof value !== "string") return true;
    const normalized = value.trim().toLowerCase();
    return normalized !== "" && normalized !== "null" && normalized !== "undefined";
  };
  const detailItems = [
    ["Occupation", enrichment?.occupation],
    ["Employer", enrichment?.employer],
    ["Party", enrichment?.political_party],
    ["Office", enrichment?.office_held],
    ["Founded", enrichment?.founded_year],
    ["Jurisdiction", enrichment?.jurisdiction],
  ].filter(([, value]) => hasDisplayValue(value));

  return (
    <section className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
      {enhancing && <div className="text-xs font-semibold text-amber-700">Enhancing...</div>}

      {loading ? (
        <div className={enhancing ? "mt-3 space-y-2" : "space-y-2"}>
          <div className="h-4 animate-pulse rounded bg-amber-100" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-amber-100" />
        </div>
      ) : enrichment ? (
        <div className={enhancing ? "mt-3 space-y-3" : "space-y-3"}>
          {enrichment.description && <p className="leading-relaxed text-amber-950">{enrichment.description}</p>}
          {enrichment.mission && (
            <div className="rounded border border-amber-200 bg-white/70 px-2 py-2">
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-amber-700">Mission</div>
              <p className="mt-1 leading-relaxed text-amber-950" title={enrichment.mission}>
                {enrichment.mission}
              </p>
            </div>
          )}
          {detailItems.length > 0 && (
            <dl className="grid grid-cols-2 gap-2">
              {detailItems.map(([label, value]) => (
                <div key={label} className="rounded border border-amber-200 bg-white/70 px-2 py-1.5">
                  <dt className="text-[10px] font-bold uppercase tracking-[0.12em] text-amber-700">{label}</dt>
                  <dd className="mt-0.5 truncate font-semibold" title={String(value)}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {enrichment.recent_news.length > 0 && (
            <div>
              <div className="text-xs font-bold uppercase tracking-[0.12em] text-amber-700">Recent News</div>
              <div className="mt-2 space-y-2">
                {enrichment.recent_news.slice(0, 3).map((item) => (
                  <a
                    key={`${item.url}-${item.headline}`}
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded border border-amber-200 bg-white/70 px-2 py-1.5 hover:border-amber-400"
                  >
                    <div className="font-semibold leading-snug" title={item.headline}>
                      {item.headline}
                    </div>
                    {item.date && (
                      <div className="mt-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-amber-700">
                        {formatDate(item.date)}
                      </div>
                    )}
                    <div className="mt-0.5 line-clamp-2 text-xs text-amber-800" title={item.summary}>
                      {item.summary}
                    </div>
                  </a>
                ))}
              </div>
            </div>
          )}
          {enrichment.sources.length > 0 && (
            <div
              className="truncate text-xs text-amber-800"
              title={enrichment.sources.map((source) => source.domain).filter(Boolean).join(", ")}
            >
              Sources: {enrichment.sources.map((source) => source.domain).filter(Boolean).slice(0, 4).join(", ")}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

function ProfileLoadingNotice({ entityName }: { entityName: string }) {
  return (
    <div className="mt-4 flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-sm">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-800" />
      <span className="min-w-0 truncate">Loading profile for {entityName}</span>
    </div>
  );
}

function EdgeTable({ title, edges, loading = false }: { title: string; edges: RecentEdge[]; loading?: boolean }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <div className="overflow-hidden rounded-md border border-slate-200">
        <table className="w-full table-fixed text-left text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="w-[42%] px-3 py-2">Counterparty</th>
              <th className="w-[22%] px-3 py-2">Amount</th>
              <th className="w-[16%] px-3 py-2">State</th>
              <th className="w-[20%] px-3 py-2">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {loading ? (
              Array.from({ length: 3 }).map((_, index) => (
                <tr key={index}>
                  <td className="px-3 py-2" colSpan={4}>
                    <div className="h-4 animate-pulse rounded bg-slate-100" />
                  </td>
                </tr>
              ))
            ) : edges.length ? (
              edges.map((edge) => (
                <tr key={edge.edge_id}>
                  <td className="truncate px-3 py-2">{edge.counterparty_name ?? "Unknown"}</td>
                  <td className="truncate px-3 py-2">{formatMoney(edge.amount)}</td>
                  <td className="truncate px-3 py-2">{titleize(edge.state) ?? "-"}</td>
                  <td className="truncate px-3 py-2">{edge.date ?? "-"}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-3 text-slate-500" colSpan={4}>
                  No rows.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InferredTable({ details }: { details: RelationshipDetail[] }) {
  return (
    <section className="mt-5">
      <div className="space-y-2">
        {details.map(({ edge, summary }) => (
          <div key={edge.id} className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
            <div className="leading-snug text-slate-900">{summary}</div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
              {edge.evidence_strength && (
                <span className="rounded-full bg-amber-50 px-1.5 py-0.5 font-semibold text-amber-800">
                  {edge.evidence_strength}
                </span>
              )}
              {edge.source_domains.length > 0 && (
                <span className="min-w-0 truncate" title={edge.source_domains.join(", ")}>
                  {edge.source_domains.join(", ")}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
