import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { LockKeyhole, Plus, Save, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";

type Permission = { code: string; name: string; description?: string | null; category: string };
type Role = { id: number; code: string; name: string; description?: string | null; is_system: boolean; is_active: boolean; permission_codes: string[] };

export default function SecurityRolesPage() {
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Role | null>(null);
  const [reason, setReason] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState(""); const [saved, setSaved] = useState(false);
  const load = useCallback(async () => { const [permissionRows, roleRows] = await Promise.all([api<Permission[]>("/admin/permissions"), api<Role[]>("/admin/security-roles")]); setPermissions(permissionRows); setRoles(roleRows); const chosen = selectedId ?? roleRows[0]?.id; setSelectedId(chosen); setDraft(roleRows.find((item) => item.id === chosen) ?? null); }, [selectedId]);
  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);
  const categories = useMemo(() => Array.from(new Set(permissions.map((item) => item.category))), [permissions]);
  const selectRole = (id: number) => { setSelectedId(id); setDraft(roles.find((role) => role.id === id) ?? null); setReason(""); };
  const toggle = (code: string) => { if (!draft || draft.code === "ADMIN") return; setDraft({ ...draft, permission_codes: draft.permission_codes.includes(code) ? draft.permission_codes.filter((item) => item !== code) : [...draft.permission_codes, code] }); };
  const save = async () => { if (!draft) return; setError(""); setSaved(false); try { await api(`/admin/security-roles/${draft.id}`, { method: "PATCH", body: JSON.stringify({ name: draft.name, description: draft.description, is_active: draft.is_active, permission_codes: draft.permission_codes, reason }) }); setSaved(true); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save permissions"); } };
  return (
    <main className="page">
      <PageHeader eyebrow="DYNAMIC RBAC" title="Security roles & permissions" description="The server enforces every permission. Frontend visibility is an additional usability control, not the security boundary." actions={<button className="button primary" onClick={() => setCreateOpen(true)}><Plus /> New security role</button>} />
      <ErrorBanner error={error} />{saved && <div className="alert success">Role permissions saved and audit-trailed.</div>}
      <section className="permissions-layout">
        <aside className="panel role-selector">{roles.map((role) => <button key={role.id} className={selectedId === role.id ? "active" : ""} onClick={() => selectRole(role.id)}><span className="role-shield"><ShieldCheck /></span><div><strong>{role.name}</strong><span>{role.code} · {role.is_active ? "Active" : "Retired"}</span></div></button>)}</aside>
        <section className="panel permissions-panel">{draft ? <><div className="permissions-heading"><div className="role-metadata"><p className="eyebrow">PERMISSION BUNDLE · {draft.code}</p><label>Role name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label>Description<textarea value={draft.description ?? ""} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>{!draft.is_system && <label className="checkbox-line"><input type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} /> Active security role</label>}</div>{draft.code === "ADMIN" && <span className="locked-role"><LockKeyhole /> All current and future permissions</span>}</div>{categories.map((category) => <div className="permission-category" key={category}><h3>{category}</h3><div className="permission-grid">{permissions.filter((item) => item.category === category).map((permission) => <label key={permission.code} className={draft.permission_codes.includes(permission.code) ? "checked" : ""}><input type="checkbox" checked={draft.permission_codes.includes(permission.code)} disabled={draft.code === "ADMIN"} onChange={() => toggle(permission.code)} /><span className="toggle-switch" /><div><strong>{permission.name}</strong><p>{permission.description}</p><code>{permission.code}</code></div></label>)}</div></div>)}<div className="permissions-save"><label>Reason for permission change<input value={reason} onChange={(event) => setReason(event.target.value)} required /></label><button className="button primary" onClick={() => void save()} disabled={!reason.trim()}><Save /> Save permission matrix</button></div></> : <EmptyState title="Select a role" detail="Choose a security role to inspect its permission bundle." />}</section>
      </section>
      {createOpen && <CreateSecurityRole permissions={permissions} onClose={() => setCreateOpen(false)} onSaved={async () => { setCreateOpen(false); await load(); }} />}
    </main>
  );
}

function CreateSecurityRole({ permissions, onClose, onSaved }: { permissions: Permission[]; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ code: "", name: "", description: "", permission_codes: [] as string[], reason: "" }); const [error, setError] = useState("");
  const toggle = (code: string) => setDraft({ ...draft, permission_codes: draft.permission_codes.includes(code) ? draft.permission_codes.filter((item) => item !== code) : [...draft.permission_codes, code] });
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api("/admin/security-roles", { method: "POST", body: JSON.stringify(draft) }); onSaved(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create security role"); } };
  return <Modal title="Create security role" onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>Role code<input value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value.toUpperCase().replaceAll(" ", "_") })} required /></label><label>Role name<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required /></label><label className="span-2">Description<textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label><fieldset className="span-2 checkbox-field"><legend>Initial permissions</legend>{permissions.map((item) => <label key={item.code}><input type="checkbox" checked={draft.permission_codes.includes(item.code)} onChange={() => toggle(item.code)} /> {item.category} · {item.name}</label>)}</fieldset><label className="span-2">Reason<input value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions span-2"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Create security role</button></div></form></Modal>;
}
