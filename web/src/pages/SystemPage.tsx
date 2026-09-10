import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArchiveRestore, CheckCircle2, DatabaseBackup, Download, FolderCog, HardDrive, RefreshCw, ServerCog, Upload, XCircle } from "lucide-react";
import { api, clearToken, download, formatDate } from "../api";
import { ErrorBanner, Modal, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";

type SystemInfo = {
  application: string;
  version: string;
  environment: string;
  database_name: string;
  backup_path: string;
  document_source: { configured_path: string; available: boolean; readable: boolean; allowed_extensions: string[] };
  settings: Record<string, string>;
};

type Backup = {
  filename: string;
  size_bytes: number;
  modified_at: string;
  manifest?: { backup_type?: string; dump_sha256?: string; documents_storage?: string } | null;
};

export default function SystemPage() {
  const { has } = useAuth();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backupOpen, setBackupOpen] = useState(false);
  const [restore, setRestore] = useState<Backup | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (has("settings.manage") || has("backups.manage")) setInfo(await api<SystemInfo>("/admin/system/info"));
    if (has("backups.manage")) setBackups(await api<Backup[]>("/admin/system/backups"));
  }, [has]);

  useEffect(() => { void load().catch((caught) => setError(caught.message)); }, [load]);

  const toggleMaintenance = async () => {
    if (!info) return;
    const next = info.settings.maintenance_mode !== "true";
    const reason = next ? "Controlled maintenance initiated by administrator" : "Controlled maintenance completed by administrator";
    try {
      await api("/admin/system/settings", {
        method: "PATCH",
        body: JSON.stringify({ values: { maintenance_mode: String(next) }, reason }),
      });
      setMessage(`Maintenance mode ${next ? "enabled" : "disabled"}.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to change maintenance mode");
    }
  };

  const upload = async (file?: File) => {
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    setBusy(true);
    try {
      await api("/admin/system/backups/upload", { method: "POST", body: data });
      setMessage("Backup uploaded. Verify it before restore.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (backup: Backup) => {
    try {
      const result = await api<{ valid: boolean; sha256: string }>(`/admin/system/backups/${encodeURIComponent(backup.filename)}/verify`);
      setMessage(result.valid ? `Verified ${backup.filename} · ${result.sha256.slice(0, 12)}…` : `Verification failed for ${backup.filename}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Verification failed");
    }
  };

  return (
    <main className="page">
      <PageHeader eyebrow="SERVER OPERATIONS" title="System administration" description="Monitor source availability, configure compliance and security controls, and perform verified backup and restore operations." actions={<button className="button secondary" onClick={() => void load()}><RefreshCw /> Refresh status</button>} />
      <ErrorBanner error={error} />
      {message && <div className="alert success">{message}</div>}

      {info && <section className="system-status-grid">
        <article className="panel status-card">
          <span className={`health-orb ${info.document_source.available && info.document_source.readable ? "healthy" : "failed"}`}>{info.document_source.available ? <CheckCircle2 /> : <XCircle />}</span>
          <p className="eyebrow">DOCUMENT SOURCE</p><h2>{info.document_source.available ? "Connected" : "Unavailable"}</h2><p>{info.document_source.configured_path}</p><small>PDF and DOCX · read-only mount</small>
        </article>
        <article className="panel status-card">
          <span className="health-orb healthy"><HardDrive /></span><p className="eyebrow">ACTIVE DATASET</p><h2>{info.database_name}</h2><p>PostgreSQL metadata and compliance records</p><small>Document files remain external</small>
        </article>
        <article className="panel status-card">
          <span className={`health-orb ${info.settings.maintenance_mode === "true" ? "warning" : "healthy"}`}><ServerCog /></span><p className="eyebrow">OPERATING MODE</p><h2>{info.settings.maintenance_mode === "true" ? "Maintenance" : "Available"}</h2><p>{info.application} · v{info.version}</p>{has("settings.manage") && <button className="button ghost" onClick={() => void toggleMaintenance()}>{info.settings.maintenance_mode === "true" ? "End maintenance" : "Enable maintenance"}</button>}
        </article>
      </section>}

      <section className="panel system-section">
        <div className="panel-heading"><div><p className="eyebrow">CONFIGURATION</p><h2>Compliance, sessions & schedules</h2></div>{has("settings.manage") && <button className="button secondary" onClick={() => setSettingsOpen(true)}><FolderCog /> Edit settings</button>}</div>
        <div className="settings-summary">
          <div><span>Active compliance threshold</span><strong>{info?.settings.active_compliance_threshold_percent ?? "80"}%</strong></div>
          <div><span>Inactivity logout</span><strong>{info?.settings.session_idle_minutes ?? "—"} min</strong></div>
          <div><span>Maximum session</span><strong>{info?.settings.session_absolute_minutes ?? "—"} min</strong></div>
          <div><span>Default training due</span><strong>{info?.settings.training_default_due_days ?? "—"} days</strong></div>
          <div><span>Automatic backup</span><strong>{info?.settings.backup_time ?? "—"} {info?.settings.backup_timezone}</strong></div>
          <div><span>Retention</span><strong>{info?.settings.backup_retention_days ?? "—"} days</strong></div>
          <div><span>Source discovery</span><strong>Every {info?.settings.source_scan_interval_minutes ?? "—"} minutes</strong></div>
          <div><span>Backup folder</span><strong>{info?.backup_path ?? "—"}</strong></div>
        </div>
        <p className="system-note">The compliance threshold drives Training Matrix scores and alerts. Session inactivity and maximum-duration limits apply to all signed-in users. The server document folder remains read-only and is selected during installation.</p>
      </section>

      {has("backups.manage") && <section className="panel system-section">
        <div className="panel-heading"><div><p className="eyebrow">DISASTER RECOVERY</p><h2>Database backups</h2><p>Backups include metadata, training evidence, audit history and a document hash inventory. The external controlled-document folder is not copied.</p></div><div className="button-row"><label className={`button secondary upload-button ${busy ? "disabled" : ""}`}><Upload /> Upload backup<input type="file" accept=".dump" disabled={busy} onChange={(event) => void upload(event.target.files?.[0])} /></label><button className="button primary" onClick={() => setBackupOpen(true)}><DatabaseBackup /> Create backup</button></div></div>
        <div className="backup-list">{backups.map((backup) => <article key={backup.filename}><span className="backup-icon"><DatabaseBackup /></span><div><strong>{backup.filename}</strong><p>{formatDate(backup.modified_at, true)} · {(backup.size_bytes / 1024 / 1024).toFixed(1)} MB · {backup.manifest?.backup_type ?? "Uploaded"}</p></div><div className="button-row"><button className="button ghost" onClick={() => void verify(backup)}>Verify</button><button className="button ghost" onClick={() => void download(`/admin/system/backups/${encodeURIComponent(backup.filename)}/download`, backup.filename)}><Download /></button><button className="button ghost danger" disabled={info?.settings.maintenance_mode !== "true"} onClick={() => setRestore(backup)}><ArchiveRestore /> Restore</button></div></article>)}</div>
      </section>}

      {settingsOpen && info && <SettingsModal info={info} onClose={() => setSettingsOpen(false)} onSaved={async () => { setSettingsOpen(false); setMessage("System configuration saved."); await load(); }} />}
      {backupOpen && <BackupModal onClose={() => setBackupOpen(false)} onSaved={async () => { setBackupOpen(false); await load(); }} />}
      {restore && <RestoreModal backup={restore} onClose={() => setRestore(null)} onRestored={() => { clearToken(); window.location.assign("/"); }} />}
    </main>
  );
}

function SettingsModal({ info, onClose, onSaved }: { info: SystemInfo; onClose: () => void; onSaved: () => void }) {
  const [values, setValues] = useState({
    active_compliance_threshold_percent: info.settings.active_compliance_threshold_percent ?? "80",
    session_idle_minutes: info.settings.session_idle_minutes ?? "15",
    session_absolute_minutes: info.settings.session_absolute_minutes ?? "480",
    backup_time: info.settings.backup_time,
    backup_timezone: info.settings.backup_timezone,
    backup_retention_days: info.settings.backup_retention_days,
    source_scan_interval_minutes: info.settings.source_scan_interval_minutes,
    training_default_due_days: info.settings.training_default_due_days,
    acknowledgement_statement: info.settings.acknowledgement_statement,
  });
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api("/admin/system/extended-settings", {
        method: "PATCH",
        body: JSON.stringify({ values, reason }),
      });
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save settings");
    }
  };

  return <Modal title="System settings" onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label>Active compliance threshold (%)<input type="number" min="0" max="100" step="1" value={values.active_compliance_threshold_percent} onChange={(event) => setValues({ ...values, active_compliance_threshold_percent: event.target.value })} /><small className="form-hint">Operators below this current-SOP score appear in Training Matrix alerts.</small></label>
    <label>Inactivity logout (minutes)<input type="number" min="5" max="240" value={values.session_idle_minutes} onChange={(event) => setValues({ ...values, session_idle_minutes: event.target.value })} /><small className="form-hint">Human activity resets this timer.</small></label>
    <label>Maximum session duration (minutes)<input type="number" min="15" max="1440" value={values.session_absolute_minutes} onChange={(event) => setValues({ ...values, session_absolute_minutes: event.target.value })} /><small className="form-hint">Must be longer than the inactivity timeout; activity does not extend this limit.</small></label>
    <label>Default training due days<input type="number" min="0" max="3650" value={values.training_default_due_days} onChange={(event) => setValues({ ...values, training_default_due_days: event.target.value })} /></label>
    <label>Daily backup time<input type="time" value={values.backup_time} onChange={(event) => setValues({ ...values, backup_time: event.target.value })} /></label>
    <label>Backup timezone<input value={values.backup_timezone} onChange={(event) => setValues({ ...values, backup_timezone: event.target.value })} /></label>
    <label>Retention days<input type="number" min="1" max="3650" value={values.backup_retention_days} onChange={(event) => setValues({ ...values, backup_retention_days: event.target.value })} /></label>
    <label>Automatic source scan (minutes)<input type="number" min="5" max="1440" value={values.source_scan_interval_minutes} onChange={(event) => setValues({ ...values, source_scan_interval_minutes: event.target.value })} /></label>
    <label className="span-2">Acknowledgement statement<textarea value={values.acknowledgement_statement} onChange={(event) => setValues({ ...values, acknowledgement_statement: event.target.value })} required /></label>
    <label className="span-2">Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label>
    <ErrorBanner error={error} />
    <div className="modal-actions span-2"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary">Save settings</button></div>
  </form></Modal>;
}

function BackupModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api("/admin/system/backups", { method: "POST", body: JSON.stringify({ reason }) });
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Backup failed");
    } finally {
      setBusy(false);
    }
  };
  return <Modal title="Create manual backup" onClose={onClose}><form className="stack-form" onSubmit={submit}><div className="signature-notice"><DatabaseBackup /><p>The PostgreSQL dataset and external-document hash inventory will be verified and recorded.</p></div><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Creating and verifying…" : "Create backup"}</button></div></form></Modal>;
}

function RestoreModal({ backup, onClose, onRestored }: { backup: Backup; onClose: () => void; onRestored: () => void }) {
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const required = `RESTORE ${backup.filename}`;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api("/admin/system/restore", { method: "POST", body: JSON.stringify({ filename: backup.filename, confirmation, reason }) });
      onRestored();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Restore failed");
    } finally {
      setBusy(false);
    }
  };
  return <Modal title="Restore into a new dataset" onClose={onClose}><form className="stack-form" onSubmit={submit}><div className="alert warning">A pre-restore backup will be created. The selected backup is restored and checked in a new dataset; the current dataset is retained.</div><label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} required /></label><label>Enter exactly: <code>{required}</code><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label><ErrorBanner error={error} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button danger" disabled={busy || confirmation !== required}>{busy ? "Verifying and restoring…" : "Restore and activate"}</button></div></form></Modal>;
}
