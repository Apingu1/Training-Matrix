import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { AlertTriangle, BellRing, BookKey, Gauge, Grid3X3, Plus, Save, Search } from "lucide-react";
import { api, formatDate, statusClass, trainingStatusLabel } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";
import type { ComplianceOverview, ControlledDocument, JobRole, TrainingAssignment } from "../types";

type MatrixUser = {
  id: number;
  username: string;
  display_name: string;
  compliance_percent: number;
  required: number;
  completed: number;
  overdue: number;
};

type LiveMatrix = {
  job_role_id?: number | null;
  selected_user_id?: number | null;
  threshold_percent: number;
  users: MatrixUser[];
  rows: {
    document: { id: number; code: string; title: string; owner_department: string };
    current_version: { id: number; version_label: string; effective_at?: string | null };
    cells: {
      user_id: number;
      status: "ASSIGNED" | "COMPLETED" | "OVERDUE" | "NOT_ASSIGNED";
      due_at?: string | null;
      completed_at?: string | null;
      individual_assignment: boolean;
    }[];
  }[];
};

type CurriculumGrid = {
  roles: { id: number; code: string; name: string; department: string }[];
  documents: {
    id: number;
    code: string;
    title: string;
    owner_department: string;
    current_version?: { id: number; version_label: string; effective_at?: string | null } | null;
    required_role_ids: number[];
  }[];
  default_due_days: number;
};

type UserCompliance = {
  user_id: number;
  display_name: string;
  required: number;
  completed: number;
  open: number;
  overdue: number;
  compliance_percent: number;
  threshold_percent: number;
  below_threshold: boolean;
};

const STATUS_OPTIONS: Array<{ value: LiveMatrix["rows"][number]["cells"][number]["status"]; label: string }> = [
  { value: "ASSIGNED", label: "Reading required" },
  { value: "COMPLETED", label: "Read and acknowledged" },
  { value: "OVERDUE", label: "Reading overdue" },
  { value: "NOT_ASSIGNED", label: "No assignment" },
];

const ALL_STATUSES = new Set(STATUS_OPTIONS.map((item) => item.value));

function matrixStatusLabel(status: string): string {
  if (status === "COMPLETED") return "Read";
  if (status === "ASSIGNED") return "Required";
  if (status === "OVERDUE") return "Overdue";
  if (status === "NOT_ASSIGNED") return "Not assigned";
  return trainingStatusLabel(status);
}

const curriculumKey = (documentId: number, roleId: number) => `${documentId}:${roleId}`;

export default function MatrixPage() {
  const { has } = useAuth();
  const [roles, setRoles] = useState<JobRole[]>([]);
  const [roleId, setRoleId] = useState<number | "">("");
  const [matrix, setMatrix] = useState<LiveMatrix | null>(null);
  const [overview, setOverview] = useState<ComplianceOverview | null>(null);
  const [curriculum, setCurriculum] = useState<CurriculumGrid | null>(null);
  const [curriculumSelection, setCurriculumSelection] = useState<Set<string>>(new Set());
  const [curriculumReason, setCurriculumReason] = useState("");
  const [curriculumSearch, setCurriculumSearch] = useState("");
  const [curriculumBusy, setCurriculumBusy] = useState(false);
  const [operatorId, setOperatorId] = useState<number | "">("");
  const [statusFilters, setStatusFilters] = useState<Set<string>>(() => new Set(ALL_STATUSES));
  const [tab, setTab] = useState<"matrix" | "curriculum" | "alerts">("matrix");
  const [historyUser, setHistoryUser] = useState<{ id: number; display_name: string } | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadOverview = useCallback(async () => {
    setOverview(await api<ComplianceOverview>("/training/compliance-overview"));
  }, []);

  const loadCurriculum = useCallback(async () => {
    const result = await api<CurriculumGrid>("/training/curriculum-grid");
    setCurriculum(result);
    const selected = new Set<string>();
    result.documents.forEach((document) => {
      document.required_role_ids.forEach((jobRoleId) => selected.add(curriculumKey(document.id, jobRoleId)));
    });
    setCurriculumSelection(selected);
  }, []);

  const loadMatrix = useCallback(async () => {
    if (!roleId) {
      setMatrix(null);
      return;
    }
    setMatrix(await api<LiveMatrix>(`/training/live-matrix?job_role_id=${roleId}`));
  }, [roleId]);

  useEffect(() => {
    const initialise = async () => {
      const roleRows = (await api<JobRole[]>("/admin/job-roles")).filter((item) => item.is_active);
      setRoles(roleRows);
      setRoleId((current) => current || roleRows[0]?.id || "");
      await Promise.all([loadOverview(), loadCurriculum()]);
    };
    void initialise().catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load training matrix"));
  }, [loadCurriculum, loadOverview]);

  useEffect(() => {
    setOperatorId("");
    void loadMatrix().catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load live matrix"));
  }, [loadMatrix]);

  const selectedUsers = useMemo(() => {
    if (!matrix) return [];
    if (!operatorId) return matrix.users;
    return matrix.users.filter((user) => user.id === operatorId);
  }, [matrix, operatorId]);

  const visibleRows = useMemo(() => {
    if (!matrix) return [];
    const userIds = new Set(selectedUsers.map((user) => user.id));
    return matrix.rows.filter((row) => row.cells.some((cell) => userIds.has(cell.user_id) && statusFilters.has(cell.status)));
  }, [matrix, selectedUsers, statusFilters]);

  const filteredCurriculumDocuments = useMemo(() => {
    if (!curriculum) return [];
    const query = curriculumSearch.trim().toLowerCase();
    if (!query) return curriculum.documents;
    return curriculum.documents.filter((document) => `${document.code} ${document.title}`.toLowerCase().includes(query));
  }, [curriculum, curriculumSearch]);

  const alerts = useMemo(
    () => overview?.users.filter((user) => user.compliance_percent < overview.threshold_percent) ?? [],
    [overview],
  );

  const toggleStatus = (status: string) => {
    setStatusFilters((current) => {
      const next = new Set(current);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  };

  const toggleCurriculum = (documentId: number, jobRoleId: number) => {
    const key = curriculumKey(documentId, jobRoleId);
    setCurriculumSelection((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const saveCurriculum = async () => {
    if (!curriculum || curriculumReason.trim().length < 3) {
      setError("Enter a reason for the curriculum change before saving.");
      return;
    }
    setCurriculumBusy(true);
    setError("");
    setMessage("");
    const selected = Array.from(curriculumSelection).map((key) => {
      const [documentFamilyId, jobRoleId] = key.split(":").map(Number);
      return { document_family_id: documentFamilyId, job_role_id: jobRoleId };
    });
    try {
      const result = await api<{
        requirements_added: number;
        requirements_reactivated: number;
        requirements_retired: number;
        training_assignments_created: number;
        training_assignments_closed: number;
      }>("/training/curriculum-grid", {
        method: "PUT",
        body: JSON.stringify({ selected, reason: curriculumReason }),
      });
      setMessage(
        `Curriculum saved. ${result.requirements_added + result.requirements_reactivated} requirements added/reactivated, ${result.requirements_retired} retired, ${result.training_assignments_created} assignments created and ${result.training_assignments_closed} closed.`,
      );
      setCurriculumReason("");
      await Promise.all([loadCurriculum(), loadOverview(), loadMatrix()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save role curriculum");
    } finally {
      setCurriculumBusy(false);
    }
  };

  return (
    <main className="page">
      <PageHeader
        eyebrow="ROLE-BASED COMPLIANCE"
        title="Training matrix"
        description="Current SOP reading requirements, active compliance and role curricula in one controlled view."
      />
      <ErrorBanner error={error} />
      {message && <div className="alert success">{message}</div>}

      <div className="tab-bar">
        <button className={tab === "matrix" ? "active" : ""} onClick={() => setTab("matrix")}><Grid3X3 /> Live matrix</button>
        <button className={tab === "curriculum" ? "active" : ""} onClick={() => setTab("curriculum")}><BookKey /> Role curriculum</button>
        <button className={tab === "alerts" ? "active" : ""} onClick={() => setTab("alerts")}><BellRing /> Alerts {alerts.length > 0 && <span className="tab-count">{alerts.length}</span>}</button>
      </div>

      {tab === "matrix" && <>
        <section className="compliance-widget-grid">
          <article className={`compliance-widget panel ${overview?.below_threshold_count ? "risk" : ""}`}>
            <span className="compliance-widget-icon"><AlertTriangle /></span>
            <div><p>Operators below {overview?.threshold_percent ?? 80}%</p><strong>{overview?.below_threshold_count ?? "—"}</strong><small>of {overview?.operator_count ?? "—"} active operators</small></div>
          </article>
          <article className="compliance-widget panel">
            <span className="compliance-widget-icon"><Gauge /></span>
            <div><p>Average active compliance</p><strong>{overview ? `${overview.average_compliance_percent}%` : "—"}</strong><small>current released SOP requirements</small></div>
          </article>
        </section>

        <section className="matrix-filter-panel panel">
          <label>Role
            <select value={roleId} onChange={(event) => setRoleId(event.target.value ? Number(event.target.value) : "")}>
              {roles.map((role) => <option value={role.id} key={role.id}>{role.department} · {role.name}</option>)}
            </select>
          </label>
          <label>Operator
            <select value={operatorId} onChange={(event) => setOperatorId(event.target.value ? Number(event.target.value) : "")}>
              <option value="">All operators in role</option>
              {matrix?.users.map((user) => <option value={user.id} key={user.id}>{user.display_name} · {user.compliance_percent}%</option>)}
            </select>
          </label>
          <fieldset className="matrix-status-filters">
            <legend>Show status</legend>
            {STATUS_OPTIONS.map((option) => <label key={option.value} className={statusFilters.has(option.value) ? "checked" : ""}><input type="checkbox" checked={statusFilters.has(option.value)} onChange={() => toggleStatus(option.value)} /><span className={statusClass(option.value)}>{option.label}</span></label>)}
          </fieldset>
        </section>

        <div className="matrix-legend"><span>Scores are based only on current released SOP reading requirements. Click an operator or status cell to open their training history.</span></div>
        {!matrix?.rows.length ? <EmptyState title="No current SOPs" detail="Release an SOP and map it to a role to populate the live matrix." /> : !selectedUsers.length ? <EmptyState title="No operators in this role" detail="Assign active users to this role to populate its live matrix." /> : !visibleRows.length ? <EmptyState title="No rows match the selected statuses" detail="Select another training status or clear the operator filter." /> : <div className="matrix-scroll"><table className="matrix-table enhanced-matrix"><thead><tr><th className="sticky-col">SOP</th><th>Version</th>{selectedUsers.map((user) => <th key={user.id}><button className="operator-heading" onClick={() => setHistoryUser({ id: user.id, display_name: user.display_name })}><strong>{user.display_name}</strong><span className={user.compliance_percent < (matrix?.threshold_percent ?? 80) ? "score-risk" : ""}>{user.compliance_percent}% compliant</span></button></th>)}</tr></thead><tbody>{visibleRows.map((row) => <tr key={row.document.id}><td className="sticky-col"><strong>{row.document.code}</strong><span>{row.document.title}</span><small>{row.document.owner_department}</small></td><td>{row.current_version.version_label}</td>{selectedUsers.map((user) => { const cell = row.cells.find((item) => item.user_id === user.id); if (!cell) return <td key={user.id}><span className="matrix-cell filtered-out">—</span></td>; const shown = statusFilters.has(cell.status); return <td key={user.id} title={`${trainingStatusLabel(cell.status)}${cell.due_at ? ` · due ${formatDate(cell.due_at)}` : ""}${cell.individual_assignment ? " · individual assignment" : ""}`}>{shown ? <button className={`matrix-cell ${statusClass(cell.status)}`} onClick={() => setHistoryUser({ id: user.id, display_name: user.display_name })}>{matrixStatusLabel(cell.status)}{cell.individual_assignment && <small>Individual</small>}</button> : <span className="matrix-cell filtered-out">—</span>}</td>; })}</tr>)}</tbody></table></div>}
      </>}

      {tab === "curriculum" && <section className="curriculum-workspace">
        <div className="curriculum-savebar panel">
          <div><p className="eyebrow">SOP × ROLE REQUIREMENTS</p><h2>Role curriculum</h2><p>Tick the SOPs each role must read and acknowledge. Forms are intentionally excluded from curricula.</p></div>
          {has("training.manage") && <div className="curriculum-save-controls"><label>Reason for changes<input value={curriculumReason} onChange={(event) => setCurriculumReason(event.target.value)} placeholder="Required audit reason" /></label><button className="button primary" disabled={curriculumBusy || curriculumReason.trim().length < 3} onClick={() => void saveCurriculum()}><Save /> {curriculumBusy ? "Saving…" : "Save changes"}</button></div>}
        </div>
        <label className="search-box curriculum-search"><Search size={17} /><input placeholder="Find SOP by number or title" value={curriculumSearch} onChange={(event) => setCurriculumSearch(event.target.value)} /></label>
        {!curriculum?.documents.length ? <EmptyState title="No SOPs available" detail="Controlled SOPs appear here once they are registered." /> : <div className="curriculum-grid-scroll"><table className="curriculum-grid-table"><thead><tr><th className="sticky-col">SOP</th>{curriculum.roles.map((role) => <th key={role.id}><span>{role.name}</span><small>{role.department}</small></th>)}</tr></thead><tbody>{filteredCurriculumDocuments.map((document) => <tr key={document.id}><td className="sticky-col"><strong>{document.code}</strong><span>{document.title}</span><small>{document.current_version ? `Current ${document.current_version.version_label}` : "No released version yet"}</small></td>{curriculum.roles.map((role) => { const checked = curriculumSelection.has(curriculumKey(document.id, role.id)); return <td key={role.id}><label className={`curriculum-check ${checked ? "checked" : ""}`} title={`${document.code} required for ${role.name}`}><input type="checkbox" checked={checked} disabled={!has("training.manage")} onChange={() => toggleCurriculum(document.id, role.id)} /><span>{checked ? "Required" : "—"}</span></label></td>; })}</tr>)}</tbody></table></div>}
      </section>}

      {tab === "alerts" && <section className="panel compliance-alerts-panel">
        <div className="panel-heading"><div><p className="eyebrow">ACTIVE COMPLIANCE ALERTS</p><h2>Below-threshold operators</h2><p>Operators appear here whenever their current released SOP compliance drops below the configured {overview?.threshold_percent ?? 80}% threshold.</p></div></div>
        {!alerts.length ? <EmptyState title="No active compliance alerts" detail={`All active operators are at or above ${overview?.threshold_percent ?? 80}% compliance.`} /> : <div className="table-wrap"><table><thead><tr><th>Operator</th><th>Compliance</th><th>Required SOPs</th><th>Outstanding</th><th>Overdue</th><th /></tr></thead><tbody>{alerts.map((user) => <tr key={user.user_id}><td><strong>{user.display_name}</strong><small>{user.username}</small></td><td><span className="status status-overdue">{user.compliance_percent}%</span></td><td>{user.required}</td><td>{user.open}</td><td>{user.overdue}</td><td><button className="button ghost" onClick={() => setHistoryUser({ id: user.user_id, display_name: user.display_name })}>View history</button></td></tr>)}</tbody></table></div>}
      </section>}

      {historyUser && <UserTrainingHistory user={historyUser} onClose={() => setHistoryUser(null)} />}
    </main>
  );
}

function UserTrainingHistory({ user, onClose }: { user: { id: number; display_name: string }; onClose: () => void }) {
  const { has } = useAuth();
  const [items, setItems] = useState<TrainingAssignment[]>([]);
  const [compliance, setCompliance] = useState<UserCompliance | null>(null);
  const [error, setError] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);

  const load = useCallback(async () => {
    const [assignmentRows, complianceResult] = await Promise.all([
      api<TrainingAssignment[]>(`/training/users/${user.id}/assignments`),
      api<UserCompliance>(`/training/users/${user.id}/compliance`),
    ]);
    setItems(assignmentRows);
    setCompliance(complianceResult);
  }, [user.id]);

  useEffect(() => { void load().catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load training history")); }, [load]);

  const waive = async (item: TrainingAssignment) => {
    const reason = window.prompt(`Reason for waiving ${item.document_code} ${item.version_label}:`);
    if (!reason) return;
    try {
      await api(`/training/assignments/${item.id}/waive`, { method: "POST", body: JSON.stringify({ reason }) });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to waive assignment");
    }
  };

  return <><Modal title={`Training history · ${user.display_name}`} onClose={onClose} wide>
    {compliance && <section className={`history-compliance ${compliance.below_threshold ? "risk" : ""}`}><div><span>Active SOP compliance</span><strong>{compliance.compliance_percent}%</strong><small>Threshold {compliance.threshold_percent}%</small></div><div><span>Current requirements</span><strong>{compliance.required}</strong><small>{compliance.completed} acknowledged · {compliance.open} outstanding</small></div><div><span>Overdue</span><strong>{compliance.overdue}</strong><small>current SOP readings</small></div></section>}
    {has("training.manage") && <div className="button-row modal-toolbar"><button className="button primary" onClick={() => setAssignOpen(true)}><Plus /> Individual assignment</button></div>}
    <ErrorBanner error={error} />
    <div className="table-wrap"><table><thead><tr><th>Document</th><th>Version</th><th>Training status</th><th>Due</th><th>Completed</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.document_code}</strong><small>{item.document_title}</small></td><td>{item.version_label}<small>{item.version_status.replaceAll("_", " ")}</small></td><td><span className={statusClass(item.status)}>{trainingStatusLabel(item.status, item.version_status)}</span>{item.closure_reason && <small>{item.closure_reason}</small>}</td><td>{formatDate(item.due_at)}</td><td>{formatDate(item.completed_at, true)}</td><td>{has("training.waive") && item.stored_status === "ASSIGNED" && <button className="button ghost danger" onClick={() => void waive(item)}>Waive</button>}</td></tr>)}</tbody></table></div>
    <div className="modal-actions"><button className="button primary" onClick={onClose}>Close history</button></div>
  </Modal>{assignOpen && <IndividualAssignmentModal user={user} onClose={() => setAssignOpen(false)} onSaved={async () => { setAssignOpen(false); await load(); }} />}</>;
}

function IndividualAssignmentModal({ user, onClose, onSaved }: { user: { id: number; display_name: string }; onClose: () => void; onSaved: () => void }) {
  const [documents, setDocuments] = useState<ControlledDocument[]>([]);
  const [versionId, setVersionId] = useState(0);
  const [dueDays, setDueDays] = useState(14);
  const [type, setType] = useState("READ_UNDERSTAND");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api<ControlledDocument[]>("/documents"), api<{ default_due_days: number }>("/training/configuration")])
      .then(([rows, configuration]) => {
        const released = rows.filter((item) => item.current_version);
        setDocuments(released);
        setVersionId(released[0]?.current_version?.id ?? 0);
        setDueDays(configuration.default_due_days);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load controlled documents"));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api("/training/assignments", { method: "POST", body: JSON.stringify({ user_id: user.id, document_version_id: versionId, due_days: dueDays, requirement_type: type, reason }) });
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create assignment");
    }
  };

  return <Modal title={`Individual assignment · ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Effective document<select value={versionId} onChange={(event) => setVersionId(Number(event.target.value))}>{documents.map((item) => <option value={item.current_version?.id} key={item.id}>{item.code} · {item.current_version?.version_label} · {item.title}</option>)}</select></label><label>Requirement type<select value={type} onChange={(event) => setType(event.target.value)}><option value="READ_UNDERSTAND">Read and understand</option><option value="AWARENESS">Awareness</option></select></label><label>Due within days<input type="number" min="0" max="3650" value={dueDays} onChange={(event) => setDueDays(Number(event.target.value))} /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={!versionId}>Assign document</button></div></form></Modal>;
}
