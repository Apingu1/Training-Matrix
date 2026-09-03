import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { AlertTriangle, CheckCircle2, FileQuestion, Files, FolderSearch, Import, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { api, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, Modal, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";
import type { SourceInventory, SourceInventoryItem } from "../types";

const classifications: Array<{ value: string; label: string }> = [
  { value: "ACTION_REQUIRED", label: "Action required" },
  { value: "UNREGISTERED", label: "Unregistered" },
  { value: "CHANGED", label: "Changed" },
  { value: "DUPLICATE", label: "Duplicates" },
  { value: "UNSUPPORTED", label: "Unsupported" },
  { value: "MISSING", label: "Missing" },
  { value: "REGISTERED", label: "Registered" },
  { value: "ALL", label: "All files" },
];
const actionRequired = new Set(["UNREGISTERED", "CHANGED", "DUPLICATE", "UNSUPPORTED", "MISSING", "SCAN_ERROR"]);
const importable = new Set(["UNREGISTERED", "DUPLICATE"]);
const documentTypes = ["SOP", "FORM", "COM", "LOG_BOOK", "QF", "ED", "AWARENESS_BRIEF", "MISC"];

type Draft = SourceInventoryItem["inferred"] & { review_due_date: string; review_interval_months: number };

const draftFor = (item: SourceInventoryItem, drafts: Record<string, Draft>): Draft =>
  drafts[item.relative_path] ?? { ...item.inferred, review_due_date: "", review_interval_months: 24 };

const compareVersions = (left: string, right: string) => {
  const leftNumber = Number(left.match(/\d+/)?.[0] ?? -1);
  const rightNumber = Number(right.match(/\d+/)?.[0] ?? -1);
  return leftNumber === rightNumber ? left.localeCompare(right, undefined, { numeric: true }) : leftNumber - rightNumber;
};

export default function SourceDiscoveryPage() {
  const { has } = useAuth();
  const [inventory, setInventory] = useState<SourceInventory | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("ACTION_REQUIRED");
  const [search, setSearch] = useState("");
  const [defaultDepartment, setDefaultDepartment] = useState("Quality Assurance");
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [importOpen, setImportOpen] = useState(false);

  const applyInventory = useCallback((next: SourceInventory) => {
    setInventory(next);
    setDrafts(Object.fromEntries(next.items.map((item) => [item.relative_path, { ...item.inferred, review_due_date: "", review_interval_months: 24 }])));
    setSelected(new Set());
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    try { applyInventory(await api<SourceInventory>("/documents/source/inventory")); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load source inventory"); }
    finally { setLoading(false); }
  }, [applyInventory]);
  useEffect(() => { void load(); }, [load]);

  const scan = async () => {
    setScanning(true); setError(""); setMessage("");
    try {
      const result = await api<SourceInventory>("/documents/source/scan", { method: "POST", body: JSON.stringify({ reason: "Manual recursive controlled-source discovery" }) });
      applyInventory(result);
      setMessage(`Source scan completed: ${result.items.length.toLocaleString()} files inventoried without copying them.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Source scan failed"); }
    finally { setScanning(false); }
  };

  const visible = useMemo(() => (inventory?.items ?? []).filter((item) => {
    const filterMatch = filter === "ALL" || (filter === "ACTION_REQUIRED" ? actionRequired.has(item.classification) : item.classification === filter);
    const needle = search.trim().toLowerCase();
    const draft = draftFor(item, drafts);
    return filterMatch && (!needle || `${item.relative_path} ${draft.code} ${draft.title} ${draft.version_label}`.toLowerCase().includes(needle));
  }), [drafts, filter, inventory, search]);

  const draftReady = (item: SourceInventoryItem) => {
    const draft = drafts[item.relative_path];
    return Boolean(item.source_sha256 && draft?.code.trim() && draft?.version_label.trim() && draft?.title.trim() && draft?.owner_department.trim());
  };
  const canSelect = (item: SourceInventoryItem) => importable.has(item.classification) && draftReady(item);
  const toggle = (item: SourceInventoryItem) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(item.relative_path)) next.delete(item.relative_path); else if (canSelect(item)) next.add(item.relative_path);
    return next;
  });
  const applyDepartment = () => {
    const value = defaultDepartment.trim(); if (!value) return;
    setDrafts((current) => Object.fromEntries(Object.entries(current).map(([path, draft]) => {
      const item = inventory?.items.find((row) => row.relative_path === path);
      return [path, item && importable.has(item.classification) ? { ...draft, owner_department: value } : draft];
    })));
  };
  const selectLikelyCurrent = () => {
    const candidates = (inventory?.items ?? []).filter((item) => item.classification === "UNREGISTERED" && canSelect(item));
    const currentByCode = new Map<string, SourceInventoryItem>();
    for (const item of candidates) {
      const draft = draftFor(item, drafts);
      const code = draft.code.trim().toUpperCase();
      const current = currentByCode.get(code);
      if (!current || compareVersions(draft.version_label, draftFor(current, drafts).version_label) > 0) currentByCode.set(code, item);
    }
    setSelected(new Set([...currentByCode.values()].map((item) => item.relative_path)));
    const omitted = candidates.length - currentByCode.size;
    setMessage(`${currentByCode.size.toLocaleString()} likely current document${currentByCode.size === 1 ? "" : "s"} selected${omitted ? `; ${omitted.toLocaleString()} older inferred version${omitted === 1 ? " was" : "s were"} left for review` : ""}.`);
  };

  if (loading) return <main className="page"><LoadingBlock label="Loading controlled-source inventory…" /></main>;
  return (
    <main className="page source-discovery-page">
      <PageHeader eyebrow="CONTROLLED SOURCE" title="Source discovery" description="Recursively inventory the approved-document folder, review detected metadata and register an authorised initial baseline without copying source files." actions={<button className="button primary" disabled={scanning} onClick={() => void scan()}><RefreshCw className={scanning ? "spin-icon" : ""} />{scanning ? "Scanning nested folders…" : "Scan source now"}</button>} />
      <ErrorBanner error={error} />{message && <div className="alert success">{message}</div>}
      {inventory?.latest_scan?.status === "FAILED" && <ErrorBanner error={`Last source scan failed: ${inventory.latest_scan.error_message ?? "Unknown source scan error"}`} />}
      {!inventory?.latest_scan ? <section className="panel"><EmptyState title="No source scan yet" detail="Run the first recursive scan to discover PDF, DOCX and unsupported files in every nested folder." /></section> : <>
        <section className="source-scan-banner panel"><div><FolderSearch /><div><strong>Last scan {formatDate(inventory.latest_scan.completed_at ?? inventory.latest_scan.started_at, true)}</strong><span>{inventory.latest_scan.trigger.toLowerCase()} · {inventory.latest_scan.status.replaceAll("_", " ").toLowerCase()}</span></div></div><p>{Number(inventory.latest_scan.counts.files_seen ?? inventory.items.length).toLocaleString()} files seen · inventory fingerprint <code>{String(inventory.latest_scan.counts.inventory_sha256 ?? "—").slice(0, 12)}…</code></p></section>
        <section className="discovery-metrics">
          <DiscoveryMetric label="Unregistered" count={inventory.counts.UNREGISTERED} tone="blue" icon={<FileQuestion />} />
          <DiscoveryMetric label="Changed" count={inventory.counts.CHANGED} tone="red" icon={<AlertTriangle />} />
          <DiscoveryMetric label="Duplicates" count={inventory.counts.DUPLICATE} tone="gold" icon={<Files />} />
          <DiscoveryMetric label="Registered" count={inventory.counts.REGISTERED} tone="green" icon={<CheckCircle2 />} />
        </section>
        <section className="panel source-inventory-panel">
          <div className="source-filter-row"><div className="segmented">{classifications.map((item) => <button key={item.value} className={filter === item.value ? "active" : ""} onClick={() => setFilter(item.value)}>{item.label}{item.value !== "ALL" && item.value !== "ACTION_REQUIRED" ? ` (${inventory.counts[item.value as SourceInventoryItem["classification"]] ?? 0})` : ""}</button>)}</div><label className="search-box"><Search size={17} /><input placeholder="Search path, code or title" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
          <div className="baseline-toolbar"><label>Default owner department<input value={defaultDepartment} onChange={(event) => setDefaultDepartment(event.target.value)} /></label><button className="button secondary" onClick={applyDepartment}>Apply to import candidates</button><button className="button secondary" onClick={selectLikelyCurrent}>Select likely current versions</button><button className="button ghost" onClick={() => setSelected(new Set())}>Clear selection</button><span>{selected.size.toLocaleString()} selected</span>{has("documents.approve") && <button className="button gold" disabled={!selected.size} onClick={() => setImportOpen(true)}><Import /> Review baseline import</button>}</div>
          <div className="source-inventory-table"><table><thead><tr><th /><th>Classification / source path</th><th>Document number</th><th>Version</th><th>Type</th><th>Owner department</th><th>Detected title</th><th>Issue date</th><th>Review due</th><th>Review cycle (months)</th></tr></thead><tbody>{visible.map((item) => {
            const draft = draftFor(item, drafts); const editable = importable.has(item.classification);
            return <tr key={item.relative_path} className={`source-row source-row-${item.classification.toLowerCase()}`}><td><input type="checkbox" aria-label={`Select ${item.relative_path}`} checked={selected.has(item.relative_path)} disabled={!canSelect(item)} onChange={() => toggle(item)} /></td><td><span className={statusClass(item.classification)}>{item.classification.replaceAll("_", " ")}</span><strong>{item.relative_path}</strong><small>{item.extension.replace(".", "").toUpperCase()} · {(item.source_size / 1024).toFixed(0)} KB · {formatDate(item.source_modified_at, true)}</small>{item.duplicate_reasons.map((reason) => <small className="source-warning" key={reason}>{reason}</small>)}{item.scan_error && <small className="source-warning">{item.scan_error}</small>}{item.registered_document && <small>Linked to {item.registered_document.code} {item.registered_document.version_label} · {item.registered_document.status.replaceAll("_", " ")}</small>}</td><td><input value={draft.code} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, code: event.target.value } })} /></td><td><input value={draft.version_label} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, version_label: event.target.value } })} /></td><td><select value={draft.document_type} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, document_type: event.target.value } })}>{documentTypes.map((type) => <option key={type}>{type}</option>)}</select></td><td><input value={draft.owner_department} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, owner_department: event.target.value } })} /></td><td><input value={draft.title} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, title: event.target.value } })} /></td><td><input type="date" value={draft.issue_date} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, issue_date: event.target.value } })} /></td><td><input type="date" value={draft.review_due_date} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, review_due_date: event.target.value } })} /></td><td><input type="number" min="1" max="120" value={draft.review_interval_months} disabled={!editable} onChange={(event) => setDrafts({ ...drafts, [item.relative_path]: { ...draft, review_interval_months: Number(event.target.value) } })} /></td></tr>;
          })}</tbody></table>{!visible.length && <EmptyState title="No files in this view" detail="Change the filter or run another source scan." />}</div>
        </section>
      </>}
      {importOpen && inventory && <BaselineImportModal items={inventory.items.filter((item) => selected.has(item.relative_path))} drafts={drafts} onClose={() => setImportOpen(false)} onImported={async (count) => { setImportOpen(false); setMessage(`${count.toLocaleString()} approved documents registered as the controlled baseline.`); await load(); }} />}
    </main>
  );
}

function DiscoveryMetric({ label, count, tone, icon }: { label: string; count: number; tone: string; icon: React.ReactNode }) {
  return <article className="metric-card"><span className={`metric-icon ${tone}`}>{icon}</span><div><p>{label}</p><strong>{count.toLocaleString()}</strong><span>source files</span></div></article>;
}

function BaselineImportModal({ items, drafts, onClose, onImported }: { items: SourceInventoryItem[]; drafts: Record<string, Draft>; onClose: () => void; onImported: (count: number) => void }) {
  const required = "IMPORT APPROVED DOCUMENT BASELINE";
  const [reason, setReason] = useState(""); const [password, setPassword] = useState(""); const [confirmation, setConfirmation] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try {
    const result = await api<{ documents_imported: number }>("/documents/source/baseline-import", { method: "POST", body: JSON.stringify({ reason, password, confirmation, items: items.map((item) => ({ relative_path: item.relative_path, expected_sha256: item.source_sha256, ...drafts[item.relative_path], issue_date: drafts[item.relative_path].issue_date || null, review_due_date: drafts[item.relative_path].review_due_date || null })) }) });
    onImported(result.documents_imported);
  } catch (caught) { setError(caught instanceof Error ? caught.message : "Baseline import failed"); } finally { setBusy(false); } };
  return <Modal title="Review approved baseline import" onClose={onClose} wide><form className="stack-form" onSubmit={submit}><div className="signature-notice"><ShieldCheck /><p>This controlled exception directly registers existing externally approved documents as released baseline versions. Every file is re-hashed and individually audited.</p></div><div className="baseline-review-list">{items.map((item) => <div key={item.relative_path}><strong>{drafts[item.relative_path].code} · {drafts[item.relative_path].version_label}</strong><span>{drafts[item.relative_path].title}</span><small>{item.relative_path}</small></div>)}</div><label>Controlled reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><label>Your password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label>Enter exactly: <code>{required}</code><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button gold" disabled={busy || confirmation !== required}>{busy ? "Verifying and importing…" : `Import ${items.length.toLocaleString()} approved documents`}</button></div></form></Modal>;
}
