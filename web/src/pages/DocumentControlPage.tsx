import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowRight, BookCopy, BookOpen, Check, Download, FilePlus2, FileText, FolderSearch, History, Pencil, Plus, Search, ShieldCheck } from "lucide-react";
import { api, download, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, Modal, PageHeader } from "../components/Common";
import DocumentViewer from "../components/DocumentViewer";
import SourceBrowser from "../components/SourceBrowser";
import { useAuth } from "../hooks/useAuth";
import type { ControlledCopy, ControlledDocument, DocumentVersion } from "../types";

const documentTypes = ["SOP", "FORM", "COM", "LOG_BOOK", "QF", "ED", "AWARENESS_BRIEF", "MISC"];

type FamilyDraft = {
  code: string;
  title: string;
  document_type: string;
  owner_department: string;
  description: string;
  review_interval_months: number;
  is_active: boolean;
  reason: string;
};

const blankFamily: FamilyDraft = {
  code: "",
  title: "",
  document_type: "SOP",
  owner_department: "",
  description: "",
  review_interval_months: 24,
  is_active: true,
  reason: "",
};

function normalisedCode(code: string): string {
  return code.trim().toUpperCase().replace(/[ _-]+/g, ".");
}

function parentSopCode(document: ControlledDocument): string | null {
  if (document.document_type !== "FORM") return null;
  const normalised = normalisedCode(document.code);
  const match = normalised.match(/^(.*\.SOP\.\d+)(?:\.F\d{1,4})$/i);
  return match?.[1] ?? null;
}

function documentOrder(document: ControlledDocument): string {
  const parent = parentSopCode(document);
  const own = normalisedCode(document.code);
  const group = parent ?? own;
  const childRank = document.document_type === "SOP" ? "0" : parent ? "1" : "2";
  return `${group}|${childRank}|${own}`;
}

export default function DocumentControlPage() {
  const { has } = useAuth();
  const [documents, setDocuments] = useState<ControlledDocument[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ControlledDocument | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [familyModal, setFamilyModal] = useState<"create" | "edit" | null>(null);
  const [versionModal, setVersionModal] = useState(false);
  const [transition, setTransition] = useState<{ version: DocumentVersion; action: string } | null>(null);
  const [viewer, setViewer] = useState<DocumentVersion | null>(null);
  const [copiesVersion, setCopiesVersion] = useState<DocumentVersion | null>(null);

  const load = useCallback(async () => {
    const rows = await api<ControlledDocument[]>("/documents?include_inactive=true");
    setDocuments(rows);
    if (!selectedId && rows[0]) setSelectedId(rows[0].id);
  }, [selectedId]);

  const loadDetail = useCallback(async () => {
    if (!selectedId) return setDetail(null);
    setDetail(await api<ControlledDocument>(`/documents/${selectedId}`));
  }, [selectedId]);

  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);
  useEffect(() => { void loadDetail().catch((caught) => setError(caught.message)); }, [loadDetail]);

  const refresh = async () => { await load(); await loadDetail(); };

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return documents
      .filter((item) => !query || `${item.code} ${item.title}`.toLowerCase().includes(query))
      .sort((a, b) => documentOrder(a).localeCompare(documentOrder(b), undefined, { numeric: true }));
  }, [documents, search]);

  const selectedParent = detail ? parentSopCode(detail) : null;
  const childForms = detail?.document_type === "SOP"
    ? documents.filter((item) => parentSopCode(item) === normalisedCode(detail.code))
    : [];

  return (
    <main className="page">
      <PageHeader eyebrow="QUALITY DOCUMENT CONTROL" title="Document control" description="Register files from the controlled server folder, manage immutable revisions and release effective versions." actions={has("documents.manage") ? <button className="button primary" onClick={() => setFamilyModal("create")}><Plus /> New document</button> : undefined} />
      <ErrorBanner error={error} />
      <section className="control-workspace">
        <aside className="control-list panel">
          <label className="search-box"><Search size={17} /><input placeholder="Find a document" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <div className="control-list-scroll controlled-hierarchy">{visible.map((item) => {
            const parent = parentSopCode(item);
            const isSop = item.document_type === "SOP";
            const isForm = item.document_type === "FORM";
            return <button key={item.id} className={`${selectedId === item.id ? "active" : ""} ${parent ? "form-child" : ""}`} onClick={() => setSelectedId(item.id)}>
              <span className={`controlled-doc-icon ${isSop ? "sop" : isForm ? "form" : "other"}`}><FileText /></span>
              <div>
                <strong>{item.code}</strong>
                {parent && <small className="document-parent-label">↳ Form of {parent}</small>}
                <span>{item.title}</span>
              </div>
              <ArrowRight />
            </button>;
          })}</div>
        </aside>

        <section className="control-detail panel">
          {!detail ? <EmptyState title="Select a document" detail="Choose a master-list record to see its controlled history." /> : <>
            <div className="control-title">
              <div>
                <div className="document-tags"><span className={detail.document_type === "SOP" ? "sop-tag" : detail.document_type === "FORM" ? "form-tag" : ""}>{detail.document_type}</span><span>{detail.owner_department}</span>{!detail.is_active && <span>Inactive family</span>}</div>
                <p className="doc-code">{detail.code}</p>
                <h2>{detail.title}</h2>
                {selectedParent && <div className="document-relation form-relation"><span className="controlled-doc-icon form"><FileText /></span><div><strong>Associated form</strong><p>This form stems from SOP <button className="inline-link" onClick={() => { const parent = documents.find((item) => normalisedCode(item.code) === selectedParent); if (parent) setSelectedId(parent.id); }}>{selectedParent}</button>.</p></div></div>}
                {detail.document_type === "SOP" && childForms.length > 0 && <div className="document-relation sop-relation"><span className="controlled-doc-icon sop"><FileText /></span><div><strong>Associated forms</strong><p>{childForms.length} controlled form{childForms.length === 1 ? "" : "s"} stem from this SOP.</p><div className="associated-form-links">{childForms.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true })).map((form) => <button key={form.id} onClick={() => setSelectedId(form.id)}>{form.code}</button>)}</div></div></div>}
                <p>{detail.description || "No additional description."}</p>
              </div>
              <div className="button-row">{has("documents.manage") && <><button className="button secondary" onClick={() => setFamilyModal("edit")}><Pencil /> Edit</button><button className="button primary" onClick={() => setVersionModal(true)}><FilePlus2 /> New revision</button></>}</div>
            </div>

            <div className="section-heading"><History /><div><h3>Version history</h3><p>Every revision remains visible to authorised Document Control and QA users.</p></div></div>
            <div className="version-timeline">{detail.versions?.map((version) => (
              <article key={version.id}>
                <div className="timeline-marker"><span /></div>
                <div className="version-card">
                  <div className="version-top"><div><strong>Version {version.version_label}</strong><span className={statusClass(version.status)}>{version.status.replaceAll("_", " ")}</span></div><span>{formatDate(version.created_at, true)}</span></div>
                  <p>{version.change_summary}</p>
                  <dl><div><dt>Source file</dt><dd>{version.relative_path}</dd></div><div><dt>Effective</dt><dd>{formatDate(version.effective_at, true)}</dd></div><div><dt>Review due</dt><dd>{formatDate(version.review_due_date)}</dd></div><div><dt>Training impact</dt><dd>{version.training_impact.replaceAll("_", " ")}</dd></div></dl>
                  <div className="version-actions"><button className="button ghost" onClick={() => setViewer(version)}><BookOpen /> View rendition</button>{has("documents.source_download") && <button className="button ghost" onClick={() => void download(`/document-versions/${version.id}/source`, version.relative_path?.split("/").pop() ?? `${detail.code}-${version.version_label}`)}><Download /> Source</button>}{has("documents.manage") && ["RELEASED", "SUPERSEDED"].includes(version.status) && <button className="button ghost" onClick={() => setCopiesVersion(version)}><BookCopy /> Controlled copies</button>}<TransitionButtons version={version} has={has} onSelect={(action) => setTransition({ version, action })} /></div>
                </div>
              </article>
            ))}</div>
          </>}
        </section>
      </section>

      {familyModal && <FamilyModal mode={familyModal} document={detail} onClose={() => setFamilyModal(null)} onSaved={async () => { setFamilyModal(null); await refresh(); }} />}
      {versionModal && detail && <VersionModal document={detail} onClose={() => setVersionModal(false)} onSaved={async () => { setVersionModal(false); await refresh(); }} />}
      {transition && <TransitionModal {...transition} onClose={() => setTransition(null)} onSaved={async () => { setTransition(null); await refresh(); }} />}
      {viewer && detail && <DocumentViewer version={viewer} code={detail.code} title={detail.title} onClose={() => setViewer(null)} />}
      {copiesVersion && detail && <ControlledCopiesModal version={copiesVersion} code={detail.code} onClose={() => setCopiesVersion(null)} />}
    </main>
  );
}

function TransitionButtons({ version, has, onSelect }: { version: DocumentVersion; has: (permission: string) => boolean; onSelect: (action: string) => void }) {
  const actions: { action: string; label: string; permission: string }[] = [];
  if (version.status === "DRAFT") actions.push({ action: "REFRESH_SOURCE", label: "Refresh draft file", permission: "documents.manage" });
  if (version.status === "DRAFT") actions.push({ action: "SUBMIT", label: "Submit for review", permission: "documents.review" });
  if (["IN_REVIEW", "APPROVED"].includes(version.status)) actions.push({ action: "RETURN_TO_DRAFT", label: "Return to draft", permission: "documents.review" });
  if (version.status === "IN_REVIEW") actions.push({ action: "APPROVE", label: "Approve", permission: "documents.approve" });
  if (version.status === "APPROVED") actions.push({ action: "RELEASE", label: "Release", permission: "documents.approve" });
  if (["RELEASED", "ISSUED_NOT_EFFECTIVE"].includes(version.status)) actions.push({ action: "OBSOLETE", label: "Make obsolete", permission: "documents.approve" });
  return <>{actions.filter((item) => has(item.permission)).map((item) => <button key={item.action} className="button secondary" onClick={() => onSelect(item.action)}><Check /> {item.label}</button>)}</>;
}

function FamilyModal({ mode, document, onClose, onSaved }: { mode: "create" | "edit"; document: ControlledDocument | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<FamilyDraft>(document ? { code: document.code, title: document.title, document_type: document.document_type, owner_department: document.owner_department, description: document.description ?? "", review_interval_months: document.review_interval_months, is_active: document.is_active, reason: "" } : blankFamily);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { await api(mode === "create" ? "/documents" : `/documents/${document?.id}`, { method: mode === "create" ? "POST" : "PATCH", body: JSON.stringify(draft) }); onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save"); }
    finally { setBusy(false); }
  };
  return <Modal title={mode === "create" ? "Create controlled document" : "Edit document metadata"} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>Document number<input value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value })} disabled={mode === "edit"} required /></label><label>Document type<select value={draft.document_type} onChange={(event) => setDraft({ ...draft, document_type: event.target.value })}>{documentTypes.map((item) => <option key={item}>{item}</option>)}</select></label><label className="span-2">Title<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required /></label><label>Owner department<input value={draft.owner_department} onChange={(event) => setDraft({ ...draft, owner_department: event.target.value })} required /></label><label>Review interval (months)<input type="number" min="1" max="120" value={draft.review_interval_months} onChange={(event) => setDraft({ ...draft, review_interval_months: Number(event.target.value) })} /></label><label className="span-2">Description<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>{mode === "edit" && <label className="span-2 checkbox-line"><input type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} /> Active master-list document</label>}<label className="span-2">Reason for change<textarea value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions span-2"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Saving…" : "Save document"}</button></div></form></Modal>;
}

function VersionModal({ document, onClose, onSaved }: { document: ControlledDocument; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ version_label: "", relative_path: "", change_summary: "", training_impact: "RETRAIN", training_impact_reason: "", issue_date: "", effective_at: "", review_due_date: "", reason: "" });
  const [browser, setBrowser] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { await api(`/documents/${document.id}/versions`, { method: "POST", body: JSON.stringify({ ...draft, issue_date: draft.issue_date || null, effective_at: draft.effective_at ? new Date(draft.effective_at).toISOString() : null, review_due_date: draft.review_due_date || null, training_impact_reason: draft.training_impact_reason || null }) }); onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to register revision"); }
    finally { setBusy(false); }
  };
  return <><Modal title={`Register a revision for ${document.code}`} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>Version label<input placeholder="V01" value={draft.version_label} onChange={(event) => setDraft({ ...draft, version_label: event.target.value })} required /></label><label>Training impact<select value={draft.training_impact} onChange={(event) => setDraft({ ...draft, training_impact: event.target.value })}><option value="RETRAIN">Retraining required</option><option value="NO_RETRAIN">No retraining required</option></select></label><label className="span-2">Controlled source file<div className="input-action"><input value={draft.relative_path} readOnly required /><button type="button" className="button secondary" onClick={() => setBrowser(true)}><FolderSearch /> Browse</button></div></label><label className="span-2">Change summary<textarea value={draft.change_summary} onChange={(event) => setDraft({ ...draft, change_summary: event.target.value })} required /></label>{draft.training_impact === "NO_RETRAIN" && <label className="span-2">No-retraining rationale<textarea value={draft.training_impact_reason} onChange={(event) => setDraft({ ...draft, training_impact_reason: event.target.value })} required /></label>}<label>Issue date<input type="date" value={draft.issue_date} onChange={(event) => setDraft({ ...draft, issue_date: event.target.value })} /></label><label>Effective date/time<input type="datetime-local" value={draft.effective_at} onChange={(event) => setDraft({ ...draft, effective_at: event.target.value })} /></label><label>Review due date<input type="date" value={draft.review_due_date} onChange={(event) => setDraft({ ...draft, review_due_date: event.target.value })} /></label><label>Registration reason<input value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><ErrorBanner error={error} /><div className="modal-actions span-2"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Verifying file…" : "Register immutable revision"}</button></div></form></Modal>{browser && <SourceBrowser onClose={() => setBrowser(false)} onSelect={(path) => { setDraft({ ...draft, relative_path: path }); setBrowser(false); }} />}</>;
}

function TransitionModal({ version, action, onClose, onSaved }: { version: DocumentVersion; action: string; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const signedAction = ["APPROVE", "RELEASE", "OBSOLETE"].includes(action);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { await api(`/document-versions/${version.id}/transition`, { method: "POST", body: JSON.stringify({ action, reason, password: signedAction ? password : null }) }); onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Transition failed"); }
    finally { setBusy(false); }
  };
  return <Modal title={`${action.replaceAll("_", " ")} version ${version.version_label}`} onClose={onClose}><form onSubmit={submit} className="stack-form"><div className="signature-notice"><ShieldCheck /><p>This controlled action is permanently recorded against the exact file hash.</p></div><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label>{signedAction && <label>Your password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>}<ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Applying…" : "Confirm action"}</button></div></form></Modal>;
}

function ControlledCopiesModal({ version, code, onClose }: { version: DocumentVersion; code: string; onClose: () => void }) {
  const [copies, setCopies] = useState<ControlledCopy[]>([]);
  const [draft, setDraft] = useState({ copy_number: "", department: "", location: "", issued_to: "", reason: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => setCopies(await api<ControlledCopy[]>(`/document-versions/${version.id}/controlled-copies`)), [version.id]);
  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);
  const issue = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { await api(`/document-versions/${version.id}/controlled-copies`, { method: "POST", body: JSON.stringify({ ...draft, issued_to: draft.issued_to || null }) }); setDraft({ copy_number: "", department: "", location: "", issued_to: "", reason: "" }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to issue controlled copy"); }
    finally { setBusy(false); }
  };
  const close = async (copy: ControlledCopy, disposition: "RETURNED" | "DESTROYED") => {
    const reason = window.prompt(`Reason this copy was ${disposition.toLowerCase()}:`);
    if (!reason) return;
    try { await api(`/controlled-copies/${copy.id}/close`, { method: "POST", body: JSON.stringify({ disposition, reason }) }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to close controlled copy"); }
  };
  return <Modal title={`Controlled copies · ${code} ${version.version_label}`} onClose={onClose} wide><div className="stack-form"><p className="muted">Track issued paper or local controlled copies. Superseded copies remain in this register until returned or destroyed.</p>{version.status === "RELEASED" && <form className="form-grid" onSubmit={issue}><label>Copy number<input value={draft.copy_number} onChange={(event) => setDraft({ ...draft, copy_number: event.target.value })} required /></label><label>Department<input value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })} required /></label><label>Controlled location<input value={draft.location} onChange={(event) => setDraft({ ...draft, location: event.target.value })} required /></label><label>Issued to<input value={draft.issued_to} onChange={(event) => setDraft({ ...draft, issued_to: event.target.value })} /></label><label className="span-2">Issue reason<input value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label><div className="modal-actions span-2"><button className="button primary" disabled={busy}>{busy ? "Issuing…" : "Issue copy"}</button></div></form>}<ErrorBanner error={error} /><div className="table-wrap"><table><thead><tr><th>Copy</th><th>Department / location</th><th>Issued</th><th>Status</th><th /></tr></thead><tbody>{copies.map((copy) => <tr key={copy.id}><td><strong>{copy.copy_number}</strong><small>{copy.issued_to || "—"}</small></td><td>{copy.department}<small>{copy.location}</small></td><td>{formatDate(copy.issued_at, true)}</td><td><span className={statusClass(copy.status)}>{copy.status}</span></td><td>{copy.status === "ISSUED" && <div className="button-row"><button className="button ghost" onClick={() => void close(copy, "RETURNED")}>Return</button><button className="button ghost" onClick={() => void close(copy, "DESTROYED")}>Destroy</button></div>}</td></tr>)}</tbody></table>{!copies.length && <EmptyState title="No controlled copies" detail="No physical copies have been issued for this version." />}</div></div></Modal>;
}
