import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Download, FileJson2, Search, ShieldCheck } from "lucide-react";
import { api, download, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, PageHeader } from "../components/Common";

type AuditEvent = {
  id: number; created_at: string; event_type: string; entity_type?: string | null; entity_id?: string | null;
  actor_username?: string | null; success: boolean; reason?: string | null; before?: unknown; after?: unknown;
  metadata?: unknown; ip_address?: string | null; request_id?: string | null;
};
type AuditResponse = { items: AuditEvent[]; total: number; page: number; page_size: number };

export default function AuditPage() {
  const [events, setEvents] = useState<AuditResponse>({ items: [], total: 0, page: 1, page_size: 50 });
  const [filters, setFilters] = useState({ event_type: "", actor: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1); const [expanded, setExpanded] = useState<number | null>(null); const [error, setError] = useState("");
  const query = new URLSearchParams({ page: String(page), page_size: "50", ...(filters.event_type && { event_type: filters.event_type }), ...(filters.actor && { actor: filters.actor }), ...(filters.date_from && { date_from: new Date(`${filters.date_from}T00:00:00`).toISOString() }), ...(filters.date_to && { date_to: new Date(`${filters.date_to}T23:59:59`).toISOString() }) }).toString();
  const load = useCallback(() => api<AuditResponse>(`/audit/events?${query}`).then(setEvents).catch((caught) => setError(caught.message)), [query]);
  useEffect(() => { void load(); }, [load]);
  const exportQuery = new URLSearchParams({ ...(filters.event_type && { event_type: filters.event_type }), ...(filters.actor && { actor: filters.actor }), ...(filters.date_from && { date_from: new Date(`${filters.date_from}T00:00:00`).toISOString() }), ...(filters.date_to && { date_to: new Date(`${filters.date_to}T23:59:59`).toISOString() }) }).toString();
  return (
    <main className="page">
      <PageHeader eyebrow="ATTRIBUTABLE HISTORY" title="Audit trail" description="Append-only records show who did what, when, why and from where. Original values remain reconstructable." actions={<div className="button-row"><button className="button secondary" onClick={() => void download(`/audit/events.csv?${exportQuery}`, "training-matrix-audit.csv")}><Download /> CSV</button><button className="button secondary" onClick={() => void download(`/audit/events.pdf?${exportQuery}`, "training-matrix-audit.pdf")}><Download /> PDF</button></div>} />
      <ErrorBanner error={error} />
      <section className="panel audit-filters"><label className="search-box"><Search /><input placeholder="Event type" value={filters.event_type} onChange={(e) => { setFilters({ ...filters, event_type: e.target.value }); setPage(1); }} /></label><label className="search-box"><ShieldCheck /><input placeholder="Actor username" value={filters.actor} onChange={(e) => { setFilters({ ...filters, actor: e.target.value }); setPage(1); }} /></label><label>From<input type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} /></label><label>To<input type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} /></label></section>
      <section className="panel audit-table">{events.items.length ? <table><thead><tr><th /><th>UTC timestamp</th><th>Event</th><th>Actor</th><th>Entity</th><th>Result</th><th>Reason</th></tr></thead><tbody>{events.items.map((event) => <AuditRow key={event.id} event={event} open={expanded === event.id} onToggle={() => setExpanded(expanded === event.id ? null : event.id)} />)}</tbody></table> : <EmptyState title="No audit events found" detail="No records match the selected filters." />}</section>
      <div className="pagination"><span>Showing {(page - 1) * 50 + (events.items.length ? 1 : 0)}–{(page - 1) * 50 + events.items.length} of {events.total}</span><div><button className="button secondary" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</button><button className="button secondary" disabled={page * 50 >= events.total} onClick={() => setPage((value) => value + 1)}>Next</button></div></div>
    </main>
  );
}

function AuditRow({ event, open, onToggle }: { event: AuditEvent; open: boolean; onToggle: () => void }) {
  return <><tr onClick={onToggle}><td>{open ? <ChevronDown /> : <ChevronRight />}</td><td>{formatDate(event.created_at, true)}</td><td><strong>{event.event_type}</strong></td><td>{event.actor_username || "SYSTEM"}</td><td>{event.entity_type} {event.entity_id}</td><td><span className={statusClass(event.success ? "SUCCESS" : "FAILED")}>{event.success ? "Success" : "Failed"}</span></td><td>{event.reason || "—"}</td></tr>{open && <tr className="audit-detail-row"><td colSpan={7}><div className="audit-detail"><div><h4><FileJson2 /> Before</h4><pre>{JSON.stringify(event.before, null, 2) || "No prior value"}</pre></div><div><h4><FileJson2 /> After</h4><pre>{JSON.stringify(event.after, null, 2) || "No resulting value"}</pre></div><div><h4>Context</h4><pre>{JSON.stringify({ metadata: event.metadata, ip_address: event.ip_address, request_id: event.request_id }, null, 2)}</pre></div></div></td></tr>}</>;
}
