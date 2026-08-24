import { useCallback, useEffect, useState } from "react";
import { BookOpen, CheckCircle2, Clock3, Search } from "lucide-react";
import { api, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";
import DocumentViewer from "../components/DocumentViewer";
import type { DocumentVersion, TrainingAssignment } from "../types";

export default function MyTrainingPage() {
  const [assignments, setAssignments] = useState<TrainingAssignment[]>([]);
  const [filter, setFilter] = useState("OPEN");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<TrainingAssignment | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<TrainingAssignment[]>("/training/my-assignments").then(setAssignments).catch((caught) => setError(caught.message)), []);
  useEffect(() => { void load(); }, [load]);

  const visible = assignments.filter((item) => {
    const matchesStatus = filter === "ALL" || (filter === "OPEN" ? ["ASSIGNED", "OVERDUE"].includes(item.status) : item.status === filter);
    const needle = search.toLowerCase();
    return matchesStatus && (!needle || `${item.document_code} ${item.document_title}`.toLowerCase().includes(needle));
  });
  const viewerVersion = selected ? {
    id: selected.document_version_id,
    family_id: selected.document_family_id,
    version_label: selected.version_label,
    status: selected.version_status,
    source_sha256: "",
    source_size: 0,
    source_modified_at: "",
    change_summary: "",
    training_impact: "RETRAIN",
    created_by: 0,
    created_at: selected.assigned_at,
  } satisfies DocumentVersion : null;

  return (
    <main className="page">
      <PageHeader eyebrow="PERSONAL CURRICULUM" title="My training" description="Read effective documents and maintain your attributable training history." />
      <ErrorBanner error={error} />
      <div className="toolbar">
        <div className="segmented">{["OPEN", "OVERDUE", "COMPLETED", "ALL"].map((item) => <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>)}</div>
        <label className="search-box"><Search size={18} /><input placeholder="Search code or title" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      </div>
      {visible.length ? <div className="training-grid">{visible.map((item) => (
        <article className={`training-card ${item.status === "OVERDUE" ? "overdue" : ""}`} key={item.id}>
          <div className="training-card-top"><span className="doc-type">{item.document_type}</span><span className={statusClass(item.status)}>{item.status}</span></div>
          <div><p className="doc-code">{item.document_code} · {item.version_label}</p><h3>{item.document_title}</h3></div>
          <div className="training-meta"><span><Clock3 /> Due {formatDate(item.due_at)}</span>{item.completed_at && <span><CheckCircle2 /> Completed {formatDate(item.completed_at, true)}</span>}</div>
          <button className={`button ${item.stored_status === "ASSIGNED" ? "primary" : "secondary"}`} onClick={() => setSelected(item)}><BookOpen size={17} /> {item.stored_status === "ASSIGNED" ? "Open & acknowledge" : "View record"}</button>
        </article>
      ))}</div> : <EmptyState title="No matching training" detail="There are no assignments in this view." />}
      {selected && viewerVersion && selected.version_status === "RELEASED" && <DocumentViewer version={viewerVersion} code={selected.document_code} title={selected.document_title} assignment={selected} onClose={() => setSelected(null)} onCompleted={load} />}
      {selected && selected.version_status !== "RELEASED" && <TrainingRecordModal assignment={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}

function TrainingRecordModal({ assignment, onClose }: { assignment: TrainingAssignment; onClose: () => void }) {
  const legacy = assignment.stored_status === "COMPLETED" ? "YY" : "XX";
  return <Modal title={`Training record · ${assignment.document_code} ${assignment.version_label}`} onClose={onClose}><div className="stack-form"><div className="signature-notice"><CheckCircle2 /><p>This is retained evidence for a superseded or obsolete controlled version.</p></div><dl className="record-list"><div><dt>Historical matrix code</dt><dd>{legacy}</dd></div><div><dt>Outcome</dt><dd>{assignment.stored_status}</dd></div><div><dt>Assigned</dt><dd>{formatDate(assignment.assigned_at, true)}</dd></div><div><dt>Completed</dt><dd>{formatDate(assignment.completed_at, true)}</dd></div><div><dt>Version state</dt><dd>{assignment.version_status.replaceAll("_", " ")}</dd></div>{assignment.acknowledgement && <><div><dt>Signed statement</dt><dd>{assignment.acknowledgement.statement}</dd></div><div><dt>Document fingerprint</dt><dd><code>{assignment.acknowledgement.source_sha256}</code></dd></div></>}</dl><div className="modal-actions"><button className="button primary" onClick={onClose}>Close record</button></div></div></Modal>;
}
