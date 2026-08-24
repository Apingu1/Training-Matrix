import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CalendarX2, KeyRound, Pencil, Plus, Shield, UserCheck, UserRoundCog, UsersRound } from "lucide-react";
import { api, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";
import type { JobRole } from "../types";

type SecurityRole = { id: number; code: string; name: string; is_active: boolean };
type UserRecord = {
  id: number; username: string; display_name: string; email?: string | null; is_active: boolean; must_change_password: boolean;
  last_login_at?: string | null; security_role: SecurityRole;
  job_roles: { id: number; job_role_id: number; code: string; name: string; department: string; effective_from: string; effective_to?: string | null }[];
};

export default function PeoplePage() {
  const { has } = useAuth();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [jobRoles, setJobRoles] = useState<JobRole[]>([]);
  const [securityRoles, setSecurityRoles] = useState<SecurityRole[]>([]);
  const [tab, setTab] = useState<"people" | "roles">(has("users.manage") ? "people" : "roles");
  const [userModal, setUserModal] = useState(false);
  const [jobModal, setJobModal] = useState(false);
  const [selected, setSelected] = useState<UserRecord | null>(null);
  const [action, setAction] = useState<"edit" | "assign" | "reset" | "toggle" | null>(null);
  const [endingRole, setEndingRole] = useState<UserRecord["job_roles"][number] | null>(null);
  const [editingJobRole, setEditingJobRole] = useState<JobRole | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const roleRows = await api<JobRole[]>("/admin/job-roles"); setJobRoles(roleRows);
    if (has("users.manage")) {
      const [userRows, securityRows] = await Promise.all([api<UserRecord[]>("/admin/users"), api<SecurityRole[]>("/admin/security-roles")]);
      setUsers(userRows); setSecurityRoles(securityRows.filter((item) => item.is_active));
    }
  }, [has]);
  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);

  return (
    <main className="page">
      <PageHeader eyebrow="PEOPLE & RESPONSIBILITIES" title="Users and job roles" description="Security roles control application access. Job roles independently define each operator’s curriculum." actions={tab === "people" && has("users.manage") ? <button className="button primary" onClick={() => setUserModal(true)}><Plus /> New user</button> : has("job_roles.manage") ? <button className="button primary" onClick={() => setJobModal(true)}><Plus /> New job role</button> : undefined} />
      <ErrorBanner error={error} />
      <div className="tab-bar">{has("users.manage") && <button className={tab === "people" ? "active" : ""} onClick={() => setTab("people")}><UsersRound /> People</button>}<button className={tab === "roles" ? "active" : ""} onClick={() => setTab("roles")}><UserRoundCog /> Operational job roles</button></div>
      {tab === "people" ? <div className="people-layout">
        <section className="panel people-table"><table><thead><tr><th>User</th><th>Security role</th><th>Job roles</th><th>Status</th><th>Last login</th></tr></thead><tbody>{users.map((user) => <tr key={user.id} className={selected?.id === user.id ? "selected" : ""} onClick={() => setSelected(user)}><td><strong>{user.display_name}</strong><span>{user.username}</span></td><td>{user.security_role.name}</td><td>{user.job_roles.filter((item) => !item.effective_to || new Date(item.effective_to) >= new Date()).map((item) => item.name).join(", ") || "No job role"}</td><td><span className={statusClass(user.is_active ? "ACTIVE" : "INACTIVE")}>{user.is_active ? "Active" : "Inactive"}</span></td><td>{formatDate(user.last_login_at, true)}</td></tr>)}</tbody></table></section>
        <aside className="panel person-detail">{selected ? <><div className="person-hero"><div className="avatar large">{selected.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</div><h2>{selected.display_name}</h2><p>{selected.email || selected.username}</p></div><dl><div><dt>Security role</dt><dd><Shield /> {selected.security_role.name}</dd></div><div><dt>Password</dt><dd>{selected.must_change_password ? "Temporary — change required" : "Permanent"}</dd></div></dl><h3>Operational roles</h3><div className="role-chips">{selected.job_roles.map((role) => <span key={role.id} className={role.effective_to ? "inactive" : ""}>{role.department} · {role.name}{!role.effective_to && <button className="chip-action" title="End role" onClick={() => setEndingRole(role)}><CalendarX2 /></button>}</span>)}</div><div className="stack-actions"><button className="button secondary" onClick={() => setAction("edit")}><Pencil /> Edit account & access</button><button className="button secondary" onClick={() => setAction("assign")}><UserCheck /> Assign job role</button><button className="button secondary" onClick={() => setAction("reset")}><KeyRound /> Reset password</button><button className={`button ${selected.is_active ? "danger" : "secondary"}`} onClick={() => setAction("toggle")}>{selected.is_active ? "Deactivate account" : "Reactivate account"}</button></div></> : <EmptyState title="Select a user" detail="Choose a person to manage their responsibilities and account." />}</aside>
      </div> : <section className="role-card-grid">{jobRoles.map((role) => <article className="panel" key={role.id}><div className="role-card-icon"><UserRoundCog /></div><span className={statusClass(role.is_active ? "ACTIVE" : "INACTIVE")}>{role.is_active ? "Active" : "Retired"}</span><p className="eyebrow">{role.department}</p><h2>{role.name}</h2><p>{role.description || "No description."}</p><code>{role.code}</code>{has("job_roles.manage") && <button className="button ghost role-edit" onClick={() => setEditingJobRole(role)}><Pencil /> Edit</button>}</article>)}</section>}
      {userModal && <CreateUserModal securityRoles={securityRoles} jobRoles={jobRoles} onClose={() => setUserModal(false)} onSaved={async () => { setUserModal(false); await load(); }} />}
      {jobModal && <CreateJobRoleModal onClose={() => setJobModal(false)} onSaved={async () => { setJobModal(false); await load(); }} />}
      {selected && action === "assign" && <AssignRoleModal user={selected} roles={jobRoles} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); setSelected(null); }} />}
      {selected && action === "edit" && <EditUserModal user={selected} securityRoles={securityRoles} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); setSelected(null); }} />}
      {selected && action === "reset" && <ResetPasswordModal user={selected} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); }} />}
      {selected && action === "toggle" && <ToggleUserModal user={selected} onClose={() => setAction(null)} onSaved={async () => { setAction(null); await load(); setSelected(null); }} />}
      {selected && endingRole && <EndRoleModal user={selected} role={endingRole} onClose={() => setEndingRole(null)} onSaved={async () => { setEndingRole(null); await load(); setSelected(null); }} />}
      {editingJobRole && <EditJobRoleModal role={editingJobRole} onClose={() => setEditingJobRole(null)} onSaved={async () => { setEditingJobRole(null); await load(); }} />}
    </main>
  );
}

function CreateUserModal({ securityRoles, jobRoles, onClose, onSaved }: { securityRoles: SecurityRole[]; jobRoles: JobRole[]; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ username: "", display_name: "", email: "", security_role_id: securityRoles[0]?.id ?? 0, temporary_password: "", job_role_ids: [] as number[], reason: "" }); const [error, setError] = useState("");
  const toggleRole = (id: number) => setDraft({ ...draft, job_role_ids: draft.job_role_ids.includes(id) ? draft.job_role_ids.filter((item) => item !== id) : [...draft.job_role_ids, id] });
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api("/admin/users", { method: "POST", body: JSON.stringify({ ...draft, email: draft.email || null }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create user"); } };
  return <Modal title="Create user account" onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>Username<input value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} required /></label><label>Display name<input value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} required /></label><label>Email<input type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></label><label>Security role<select value={draft.security_role_id} onChange={(e) => setDraft({ ...draft, security_role_id: Number(e.target.value) })}>{securityRoles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><label className="span-2">Temporary password<input type="password" value={draft.temporary_password} onChange={(e) => setDraft({ ...draft, temporary_password: e.target.value })} required /><span className="form-hint">12+ characters including upper/lower case, number and special character.</span></label><fieldset className="span-2 checkbox-field"><legend>Initial operational job roles</legend>{jobRoles.filter((role) => role.is_active).map((role) => <label key={role.id}><input type="checkbox" checked={draft.job_role_ids.includes(role.id)} onChange={() => toggleRole(role.id)} /> {role.department} · {role.name}</label>)}</fieldset><label className="span-2">Reason<textarea value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions span-2"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Create account</button></div></form></Modal>;
}

function CreateJobRoleModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ code: "", name: "", department: "", description: "", reason: "" }); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api("/admin/job-roles", { method: "POST", body: JSON.stringify(draft) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create job role"); } };
  return <Modal title="Create operational job role" onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Role code<input placeholder="PRODUCTION_OPERATOR" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value.toUpperCase().replaceAll(" ", "_") })} required /></label><label>Role name<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required /></label><label>Department<input value={draft.department} onChange={(e) => setDraft({ ...draft, department: e.target.value })} required /></label><label>Description<textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label><label>Reason<textarea value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Create role</button></div></form></Modal>;
}

function EditJobRoleModal({ role, onClose, onSaved }: { role: JobRole; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ name: role.name, department: role.department, description: role.description ?? "", is_active: role.is_active, reason: "" }); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/job-roles/${role.id}`, { method: "PATCH", body: JSON.stringify(draft) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to update job role"); } };
  return <Modal title={`Edit ${role.name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Role name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label><label>Department<input value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })} required /></label><label>Description<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label><label className="checkbox-line"><input type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} /> Active job role</label><label>Reason<textarea value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Save role</button></div></form></Modal>;
}

function EditUserModal({ user, securityRoles, onClose, onSaved }: { user: UserRecord; securityRoles: SecurityRole[]; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ display_name: user.display_name, email: user.email ?? "", security_role_id: user.security_role.id, reason: "" }); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ ...draft, email: draft.email || null }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to update account"); } };
  return <Modal title={`Edit ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Display name<input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} required /></label><label>Email<input type="email" value={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.value })} /></label><label>Security role<select value={draft.security_role_id} onChange={(event) => setDraft({ ...draft, security_role_id: Number(event.target.value) })}>{securityRoles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><label>Reason<textarea value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><p className="form-hint">Changing the security role revokes the user’s active sessions.</p><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Save account</button></div></form></Modal>;
}

function EndRoleModal({ user, role, onClose, onSaved }: { user: UserRecord; role: UserRecord["job_roles"][number]; onClose: () => void; onSaved: () => void }) {
  const [effectiveTo, setEffectiveTo] = useState(new Date().toISOString().slice(0, 10)); const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/user-job-roles/${role.id}/end`, { method: "POST", body: JSON.stringify({ effective_to: effectiveTo, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to end job role"); } };
  return <Modal title={`End ${role.name} for ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Final effective date<input type="date" value={effectiveTo} min={role.effective_from} onChange={(event) => setEffectiveTo(event.target.value)} required /></label><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><p className="form-hint">The role remains active through this date. Open training is reconciled after it ends; completed history remains.</p><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button danger">End role</button></div></form></Modal>;
}

function AssignRoleModal({ user, roles, onClose, onSaved }: { user: UserRecord; roles: JobRole[]; onClose: () => void; onSaved: () => void }) {
  const [roleId, setRoleId] = useState(roles.find((role) => role.is_active)?.id ?? 0); const [effective, setEffective] = useState(new Date().toISOString().slice(0, 10)); const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/users/${user.id}/job-roles`, { method: "POST", body: JSON.stringify({ job_role_id: roleId, effective_from: effective, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to assign role"); } };
  return <Modal title={`Assign job role to ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Job role<select value={roleId} onChange={(e) => setRoleId(Number(e.target.value))}>{roles.filter((role) => role.is_active).map((role) => <option value={role.id} key={role.id}>{role.department} · {role.name}</option>)}</select></label><label>Effective from<input type="date" value={effective} onChange={(e) => setEffective(e.target.value)} /></label><label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></label><p className="form-hint">Current requirements for this role will be assigned automatically on the effective date.</p><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Assign role</button></div></form></Modal>;
}

function ResetPasswordModal({ user, onClose, onSaved }: { user: UserRecord; onClose: () => void; onSaved: () => void }) {
  const [password, setPassword] = useState(""); const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/users/${user.id}/reset-password`, { method: "POST", body: JSON.stringify({ temporary_password: password, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to reset password"); } };
  return <Modal title={`Reset password for ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Temporary password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label><label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></label><p className="form-hint">All existing sessions will be revoked. The user must change this password at next sign-in.</p><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Reset password</button></div></form></Modal>;
}

function ToggleUserModal({ user, onClose, onSaved }: { user: UserRecord; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !user.is_active, reason }) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to update account"); } };
  return <Modal title={`${user.is_active ? "Deactivate" : "Reactivate"} ${user.display_name}`} onClose={onClose}><form className="stack-form" onSubmit={submit}><label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></label>{user.is_active && <p className="form-hint">All active sessions will be revoked immediately. Historical training remains intact.</p>}<ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className={user.is_active ? "button danger" : "button primary"}>Confirm</button></div></form></Modal>;
}
