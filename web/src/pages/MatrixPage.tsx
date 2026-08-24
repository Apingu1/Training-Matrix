import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BookKey, Grid3X3, Pencil, Plus, Settings2 } from "lucide-react";
import { api, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";
import type { ControlledDocument, JobRole, Requirement, TrainingAssignment } from "../types";

type Matrix = {
  job_role: JobRole;
  users: { id: number; username: string; display_name: string }[];
  rows: {
    requirement: Requirement;
    current_version?: { id: number; version_label: string; effective_at?: string | null } | null;
    cells: { user_id: number; status: string; due_at?: string | null; completed_at?: string | null }[];
  }[];
};

function legacyCode(status: string): string {
  if (status === "COMPLETED") return "Y";
  if (["ASSIGNED", "OVERDUE", "NOT_ASSIGNED"].includes(status)) return "X";
  if (status === "REFERENCE") return "—";
  return status.slice(0, 2);
}

export default function MatrixPage() {
  const { has } = useAuth();
  const [roles, setRoles] = useState<JobRole[]>([]);
  const [roleId, setRoleId] = useState<number | null>(null);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [documents, setDocuments] = useState<ControlledDocument[]>([]);
  const [tab, setTab] = useState<"matrix" | "curriculum">("matrix");
  const [addOpen, setAddOpen] = useState(false);
  const [retiring, setRetiring] = useState<Requirement | null>(null);
  const [editing, setEditing] = useState<Requirement | null>(null);
  const [historyUser, setHistoryUser] = useState<{ id: number; display_name: string } | null>(null);
  const [error, setError] = useState("");

  const loadRoles = useCallback(() => api<JobRole[]>("/admin/job-roles").then((rows) => { setRoles(rows.filter((item) => item.is_active)); if (!roleId && rows[0]) setRoleId(rows[0].id); }), [roleId]);
  const loadRole = useCallback(async () => {
    if (!roleId) return;
    const [matrixResult, requirementResult] = await Promise.all([
      api<Matrix>(`/training/matrix/${roleId}`),
      api<Requirement[]>(`/training/requirements?job_role_id=${roleId}&include_inactive=true`),
    ]);
    setMatrix(matrixResult); setRequirements(requirementResult);
  }, [roleId]);
  useEffect(() => { void loadRoles().catch((caught) => setError(caught.message)); api<ControlledDocument[]>("/documents").then(setDocuments).catch(() => undefined); }, [loadRoles]);
  useEffect(() => { void loadRole().catch((caught) => setError(caught.message)); }, [loadRole]);
  const refresh = async () => { await loadRole(); };

  return (
    <main className="page">
      <PageHeader eyebrow="ROLE-BASED COMPLIANCE" title="Training matrix" description="Requirements are defined once against a job role and automatically applied to current and future operators." actions={<select value={roleId ?? ""} onChange={(event) => setRoleId(Number(event.target.value))}>{roles.map((role) => <option value={role.id} key={role.id}>{role.department} · {role.name}</option>)}</select>} />
      <ErrorBanner error={error} />
      <div className="tab-bar"><button className={tab === "matrix" ? "active" : ""} onClick={() => setTab("matrix")}><Grid3X3 /> Live matrix</button><button className={tab === "curriculum" ? "active" : ""} onClick={() => setTab("curriculum")}><BookKey /> Role curriculum</button></div>
      {tab === "matrix" ? <>
        <div className="matrix-legend"><span><strong className="legacy x">X</strong> Effective version not yet read</span><span><strong className="legacy y">Y</strong> Effective version read</span><span><strong className="legacy overdue">X</strong> Overdue</span><span>Superseded XX/YY evidence is retained in each user’s history. Trainer code T has been removed.</span></div>
        {!matrix?.rows.length ? <EmptyState title="No curriculum defined" detail="Add controlled documents to this role to generate its live matrix." /> : <div className="matrix-scroll"><table className="matrix-table"><thead><tr><th className="sticky-col">Controlled document</th><th>Version</th>{matrix.users.map((user) => <th key={user.id}><div className="vertical-name">{user.display_name}</div></th>)}</tr></thead><tbody>{matrix.rows.map((row) => <tr key={row.requirement.id}><td className="sticky-col"><strong>{row.requirement.document_code}</strong><span>{row.requirement.document_title}</span><small>{row.requirement.requirement_type.replaceAll("_", " ")}</small></td><td>{row.current_version?.version_label ?? "No effective version"}</td>{row.cells.map((cell) => <td key={cell.user_id} title={`${cell.status}${cell.due_at ? ` · due ${formatDate(cell.due_at)}` : ""}`}><button className={`matrix-cell ${statusClass(cell.status)}`} onClick={() => { const user = matrix.users.find((item) => item.id === cell.user_id); if (user) setHistoryUser(user); }}>{legacyCode(cell.status)}</button></td>)}</tr>)}</tbody></table></div>}
      </> : <section className="panel curriculum-panel">
        <div className="panel-heading"><div><p className="eyebrow">PREDEFINED REQUIREMENTS</p><h2>{matrix?.job_role.name ?? "Role"} curriculum</h2></div>{has("training.manage") && <button className="button primary" onClick={() => setAddOpen(true)}><Plus /> Add requirement</button>}</div>
        {requirements.length ? <div className="curriculum-list">{requirements.map((item) => <article key={item.id} className={!item.is_active ? "inactive" : ""}><span className="doc-type">{item.requirement_type === "CONTROLLED_COPY" ? "COPY" : item.requirement_type.slice(0, 3)}</span><div><strong>{item.document_code}</strong><h3>{item.document_title}</h3><p>{item.requirement_type.replaceAll("_", " ")} · Due within {item.due_days} days · {item.is_active ? "Active" : "Retired"}</p></div>{has("training.manage") && <div className="button-row"><button className="button ghost" onClick={() => setEditing(item)}><Pencil /> {item.is_active ? "Edit" : "Reactivate"}</button>{item.is_active && <button className="button ghost danger" onClick={() => setRetiring(item)}>Retire</button>}</div>}</article>)}</div> : <EmptyState title="No requirements" detail="This job role does not yet have a controlled-document curriculum." />}
      </section>}
      {addOpen && roleId && <RequirementModal roleId={roleId} documents={documents} onClose={() => setAddOpen(false)} onSaved={async () => { setAddOpen(false); await refresh(); }} />}
      {retiring && <RetireRequirement requirement={retiring} onClose={() => setRetiring(null)} onSaved={async () => { setRetiring(null); await refresh(); }} />}
      {editing && <EditRequirement requirement={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await refresh(); }} />}
      {historyUser && <UserTrainingHistory user={historyUser} onClose={() => setHistoryUser(null)} />}
    </main>
  );
}

function RequirementModal({ roleId, documents, onClose, onSaved }: { roleId: number; documents: ControlledDocument[]; onClose: () => void; onSaved: () => void }) {
  const [documentId, setDocumentId] = useState(documents[0]?.id ?? 0);
  const [type, setType] = useState("READ_UNDERSTAND"); const [dueDays, setDueDays] = useState(14); const [reason, setReason] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { api<{ default_due_days: number }>("/training/configuration").then((result) => setDueDays(result.default_due_days)).catch(() => undefined); }, []);
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try { await api("/training/requirements", { method: "POST", body: JSON.stringify({ job_role_id: roleId, document_family_id: documentId, requirement_type: type, due_days: dueDays, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to add requirement"); } finally { setBusy(false); } };
  return <Modal title="Add role requirement" onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Controlled document<select value={documentId} onChange={(e) => setDocumentId(Number(e.target.value))}>{documents.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.title}</option>)}</select></label><label>Requirement type<select value={type} onChange={(e) => setType(e.target.value)}><option value="READ_UNDERSTAND">Read and understand</option><option value="AWARENESS">Awareness</option><option value="REFERENCE_ONLY">Reference only</option><option value="CONTROLLED_COPY">Controlled-copy distribution</option></select></label><label>Due within days<input type="number" min="0" max="3650" value={dueDays} onChange={(e) => setDueDays(Number(e.target.value))} /></label><label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Applying…" : "Add to curriculum"}</button></div></form></Modal>;
}

function RetireRequirement({ requirement, onClose, onSaved }: { requirement: Requirement; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/training/requirements/${requirement.id}`, { method: "PATCH", body: JSON.stringify({ is_active: false, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to retire requirement"); } };
  return <Modal title="Retire curriculum requirement" onClose={onClose}><form className="stack-form" onSubmit={submit}><div className="signature-notice"><Settings2 /><p>Future operators will no longer receive {requirement.document_code}. Historical completions are retained.</p></div><label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button danger">Retire requirement</button></div></form></Modal>;
}

function EditRequirement({ requirement, onClose, onSaved }: { requirement: Requirement; onClose: () => void; onSaved: () => void }) {
  const [type, setType] = useState(requirement.requirement_type); const [dueDays, setDueDays] = useState(requirement.due_days); const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/training/requirements/${requirement.id}`, { method: "PATCH", body: JSON.stringify({ requirement_type: type, due_days: dueDays, is_active: true, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to update requirement"); } };
  return <Modal title={`${requirement.is_active ? "Edit" : "Reactivate"} ${requirement.document_code}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Requirement type<select value={type} onChange={(event) => setType(event.target.value)}><option value="READ_UNDERSTAND">Read and understand</option><option value="AWARENESS">Awareness</option><option value="REFERENCE_ONLY">Reference only</option><option value="CONTROLLED_COPY">Controlled-copy distribution</option></select></label><label>Due within days<input type="number" min="0" max="3650" value={dueDays} onChange={(event) => setDueDays(Number(event.target.value))} /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Save requirement</button></div></form></Modal>;
}

function UserTrainingHistory({ user, onClose }: { user: { id: number; display_name: string }; onClose: () => void }) {
  const { has } = useAuth(); const [items, setItems] = useState<TrainingAssignment[]>([]); const [error, setError] = useState(""); const [assignOpen, setAssignOpen] = useState(false);
  const load = useCallback(() => api<TrainingAssignment[]>(`/training/users/${user.id}/assignments`).then(setItems), [user.id]);
  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);
  const waive = async (item: TrainingAssignment) => { const reason = window.prompt(`Reason for waiving ${item.document_code} ${item.version_label}:`); if (!reason) return; try { await api(`/training/assignments/${item.id}/waive`, { method: "POST", body: JSON.stringify({ reason }) }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to waive assignment"); } };
  return <><Modal title={`Training history · ${user.display_name}`} onClose={onClose} wide>{has("training.manage") && <div className="button-row modal-toolbar"><button className="button primary" onClick={() => setAssignOpen(true)}><Plus /> Individual assignment</button></div>}<ErrorBanner error={error} /><div className="table-wrap"><table><thead><tr><th>Document</th><th>Version</th><th>Status</th><th>Due</th><th>Completed</th><th>Historical code</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.document_code}</strong><small>{item.document_title}</small></td><td>{item.version_label}<small>{item.version_status.replaceAll("_", " ")}</small></td><td><span className={statusClass(item.status)}>{item.status}</span></td><td>{formatDate(item.due_at)}</td><td>{formatDate(item.completed_at, true)}</td><td>{item.version_status === "SUPERSEDED" ? (item.stored_status === "COMPLETED" ? "YY" : "XX") : (item.stored_status === "COMPLETED" ? "Y" : "X")}</td><td>{has("training.waive") && item.stored_status === "ASSIGNED" && <button className="button ghost danger" onClick={() => void waive(item)}>Waive</button>}</td></tr>)}</tbody></table></div><div className="modal-actions"><button className="button primary" onClick={onClose}>Close history</button></div></Modal>{assignOpen && <IndividualAssignmentModal user={user} onClose={() => setAssignOpen(false)} onSaved={async () => { setAssignOpen(false); await load(); }} />}</>;
}

function IndividualAssignmentModal({ user, onClose, onSaved }: { user: { id: number; display_name: string }; onClose: () => void; onSaved: () => void }) {
  const [documents, setDocuments] = useState<ControlledDocument[]>([]); const [versionId, setVersionId] = useState(0); const [dueDays, setDueDays] = useState(14); const [type, setType] = useState("READ_UNDERSTAND"); const [reason, setReason] = useState(""); const [error, setError] = useState("");
  useEffect(() => { Promise.all([api<ControlledDocument[]>("/documents"), api<{ default_due_days: number }>("/training/configuration")]).then(([rows, configuration]) => { const released = rows.filter((item) => item.current_version); setDocuments(released); setVersionId(released[0]?.current_version?.id ?? 0); setDueDays(configuration.default_due_days); }).catch((caught) => setError(caught.message)); }, []);
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api("/training/assignments", { method: "POST", body: JSON.stringify({ user_id: user.id, document_version_id: versionId, due_days: dueDays, requirement_type: type, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create assignment"); } };
  return <Modal title={`Individual assignment · ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Effective document<select value={versionId} onChange={(event) => setVersionId(Number(event.target.value))}>{documents.map((item) => <option value={item.current_version?.id} key={item.id}>{item.code} · {item.current_version?.version_label} · {item.title}</option>)}</select></label><label>Requirement type<select value={type} onChange={(event) => setType(event.target.value)}><option value="READ_UNDERSTAND">Read and understand</option><option value="AWARENESS">Awareness</option></select></label><label>Due within days<input type="number" min="0" max="3650" value={dueDays} onChange={(event) => setDueDays(Number(event.target.value))} /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={!versionId}>Assign document</button></div></form></Modal>;
}
