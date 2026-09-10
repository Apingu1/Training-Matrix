import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, BellRing, Clock3, MailCheck, RefreshCw, Send, ShieldCheck, UsersRound } from "lucide-react";
import { api, formatDate, statusClass } from "../api";
import { EmptyState, ErrorBanner, PageHeader } from "../components/Common";

type NotificationSettings = {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_security: "STARTTLS" | "SSL" | "NONE";
  smtp_username: string;
  smtp_password_configured: boolean;
  sender_name: string;
  sender_email: string;
  overdue_frequency_days: number;
  enabled_since?: string | null;
  active_user_count: number;
  users_with_email_count: number;
  users_without_email_count: number;
};

type NotificationDelivery = {
  id: number;
  notification_type: "NEW_ASSIGNMENT" | "OVERDUE" | "BELOW_THRESHOLD" | "TEST";
  recipient_email: string;
  subject: string;
  status: "PENDING" | "SENT" | "FAILED";
  attempt_count: number;
  scheduled_for: string;
  last_attempt_at?: string | null;
  sent_at?: string | null;
  error_message?: string | null;
  created_at: string;
};

type SettingsDraft = {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_security: NotificationSettings["smtp_security"];
  smtp_username: string;
  smtp_password: string;
  clear_smtp_password: boolean;
  sender_name: string;
  sender_email: string;
  overdue_frequency_days: number;
  reason: string;
};

const blankDraft: SettingsDraft = {
  enabled: false,
  smtp_host: "",
  smtp_port: 587,
  smtp_security: "STARTTLS",
  smtp_username: "",
  smtp_password: "",
  clear_smtp_password: false,
  sender_name: "Eaststone Training Matrix",
  sender_email: "",
  overdue_frequency_days: 1,
  reason: "",
};

const deliveryLabel = (value: NotificationDelivery["notification_type"]) => {
  if (value === "NEW_ASSIGNMENT") return "New assignment";
  if (value === "OVERDUE") return "Overdue reminder";
  if (value === "BELOW_THRESHOLD") return "Below threshold";
  return "Configuration test";
};

export default function NotificationSettingsPage() {
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [draft, setDraft] = useState<SettingsDraft>(blankDraft);
  const [deliveries, setDeliveries] = useState<NotificationDelivery[]>([]);
  const [testRecipient, setTestRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const [current, history] = await Promise.all([
      api<NotificationSettings>("/admin/notifications/settings"),
      api<NotificationDelivery[]>("/admin/notifications/deliveries?limit=100"),
    ]);
    setSettings(current);
    setDeliveries(history);
    setDraft({
      enabled: current.enabled,
      smtp_host: current.smtp_host,
      smtp_port: current.smtp_port,
      smtp_security: current.smtp_security,
      smtp_username: current.smtp_username,
      smtp_password: "",
      clear_smtp_password: false,
      sender_name: current.sender_name,
      sender_email: current.sender_email,
      overdue_frequency_days: current.overdue_frequency_days,
      reason: "",
    });
    setTestRecipient((value) => value || current.sender_email);
  }, []);

  useEffect(() => {
    void load().catch((caught) => setError(caughtMessage(caught, "Unable to load notification settings")));
  }, [load]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await api<NotificationSettings>("/admin/notifications/settings", {
        method: "PATCH",
        body: JSON.stringify({
          ...draft,
          smtp_password: draft.smtp_password || null,
        }),
      });
      setSettings(saved);
      setDraft((current) => ({ ...current, smtp_password: "", clear_smtp_password: false, reason: "" }));
      setMessage(`Email notifications ${saved.enabled ? "enabled" : "saved but switched off"}.`);
      await load();
    } catch (caught) {
      setError(caughtMessage(caught, "Unable to save notification settings"));
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setTestBusy(true);
    setError("");
    setMessage("");
    try {
      await api("/admin/notifications/test", {
        method: "POST",
        body: JSON.stringify({ recipient_email: testRecipient }),
      });
      setMessage(`Test email sent to ${testRecipient}.`);
      await load();
    } catch (caught) {
      setError(caughtMessage(caught, "Unable to send the test email"));
    } finally {
      setTestBusy(false);
    }
  };

  const runNow = async () => {
    setRunBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<{ queued: number; sent: number; failed: number }>("/admin/notifications/run", {
        method: "POST",
      });
      setMessage(`Notification cycle complete: ${result.queued} queued, ${result.sent} sent and ${result.failed} failed.`);
      await load();
    } catch (caught) {
      setError(caughtMessage(caught, "Unable to run notifications"));
    } finally {
      setRunBusy(false);
    }
  };

  return (
    <main className="page notification-page">
      <PageHeader
        eyebrow="TRAINING COMMUNICATIONS"
        title="Notification settings"
        description="Configure assignment, overdue and below-threshold email alerts, then review their delivery history."
        actions={<button className="button secondary" onClick={() => void load()}><RefreshCw /> Refresh</button>}
      />
      <ErrorBanner error={error} />
      {message && <div className="alert success">{message}</div>}

      <section className="notification-status-grid">
        <article className="panel status-card">
          <span className={`health-orb ${settings?.enabled ? "healthy" : "warning"}`}><BellRing /></span>
          <p className="eyebrow">EMAIL ALERTS</p>
          <h2>{settings?.enabled ? "Enabled" : "Switched off"}</h2>
          <p>{settings?.enabled ? "Automatic notification cycles run every minute." : "Configuration can be tested before alerts are enabled."}</p>
          <small>{settings?.enabled_since ? `Enabled ${formatDate(settings.enabled_since, true)}` : "No activation recorded"}</small>
        </article>
        <article className="panel status-card">
          <span className={`health-orb ${settings?.users_without_email_count ? "warning" : "healthy"}`}><UsersRound /></span>
          <p className="eyebrow">EMAIL COVERAGE</p>
          <h2>{settings?.users_with_email_count ?? "—"} / {settings?.active_user_count ?? "—"}</h2>
          <p>Active users have a valid email address recorded.</p>
          <small>{settings?.users_without_email_count ?? "—"} without an email address</small>
        </article>
        <article className="panel status-card">
          <span className="health-orb healthy"><Clock3 /></span>
          <p className="eyebrow">OVERDUE REMINDERS</p>
          <h2>Every {settings?.overdue_frequency_days ?? "—"} day{settings?.overdue_frequency_days === 1 ? "" : "s"}</h2>
          <p>Outstanding overdue readings are combined into one email per operator.</p>
          <small>New assignments are also consolidated by operator</small>
        </article>
      </section>

      <form className="panel system-section notification-configuration" onSubmit={save}>
        <div className="panel-heading">
          <div><p className="eyebrow">SMTP ACCOUNT</p><h2>Email delivery configuration</h2><p>Use Eaststone's approved mailbox or SMTP relay. The saved password is encrypted and never displayed again.</p></div>
          <label className={`notification-toggle ${draft.enabled ? "checked" : ""}`}>
            <input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />
            <span className="toggle-switch" />
            <strong>{draft.enabled ? "Notifications on" : "Notifications off"}</strong>
          </label>
        </div>

        <div className="form-grid notification-form-grid">
          <label>SMTP server<input value={draft.smtp_host} onChange={(event) => setDraft({ ...draft, smtp_host: event.target.value })} placeholder="smtp.office365.com" required={draft.enabled} /></label>
          <label>Port<input type="number" min="1" max="65535" value={draft.smtp_port} onChange={(event) => setDraft({ ...draft, smtp_port: Number(event.target.value) })} required /></label>
          <label>Connection security<select value={draft.smtp_security} onChange={(event) => setDraft({ ...draft, smtp_security: event.target.value as SettingsDraft["smtp_security"] })}><option value="STARTTLS">STARTTLS</option><option value="SSL">SSL / TLS</option><option value="NONE">None — internal trusted relay only</option></select></label>
          <label>SMTP username<input value={draft.smtp_username} onChange={(event) => setDraft({ ...draft, smtp_username: event.target.value })} autoComplete="username" placeholder="notifications@company.co.uk" /></label>
          <label>SMTP password<input type="password" value={draft.smtp_password} onChange={(event) => setDraft({ ...draft, smtp_password: event.target.value, clear_smtp_password: false })} autoComplete="new-password" placeholder={settings?.smtp_password_configured ? "Saved — leave blank to retain" : "Enter account or app password"} /><small className="form-hint">{settings?.smtp_password_configured ? "An encrypted password is currently saved." : "No SMTP password is saved."}</small></label>
          <label className="checkbox-line notification-clear-secret"><input type="checkbox" checked={draft.clear_smtp_password} onChange={(event) => setDraft({ ...draft, clear_smtp_password: event.target.checked, smtp_password: event.target.checked ? "" : draft.smtp_password })} /> Clear the saved SMTP password</label>
          <label>Sender name<input value={draft.sender_name} onChange={(event) => setDraft({ ...draft, sender_name: event.target.value })} required /></label>
          <label>Sender email<input type="email" value={draft.sender_email} onChange={(event) => setDraft({ ...draft, sender_email: event.target.value })} required={draft.enabled} /></label>
          <label>Overdue reminder frequency<select value={draft.overdue_frequency_days} onChange={(event) => setDraft({ ...draft, overdue_frequency_days: Number(event.target.value) })}><option value={1}>Every day</option><option value={2}>Every 2 days</option><option value={3}>Every 3 days</option><option value={7}>Every 7 days</option><option value={14}>Every 14 days</option><option value={30}>Every 30 days</option></select></label>
          <label className="span-2">Reason for change<textarea value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} required /></label>
        </div>
        <div className="notification-security-note"><ShieldCheck /><span>SMTP passwords are encrypted using the installation secret. Password values are excluded from API responses and audit records.</span></div>
        <div className="modal-actions"><button className="button primary" disabled={busy}>{busy ? "Saving…" : "Save notification settings"}</button></div>
      </form>

      <section className="notification-actions-grid">
        <article className="panel system-section">
          <div className="panel-heading"><div><p className="eyebrow">CONNECTION TEST</p><h2>Send a test email</h2><p>Save the SMTP settings first, then confirm delivery to a monitored address.</p></div><MailCheck /></div>
          <div className="notification-inline-action"><label>Test recipient<input type="email" value={testRecipient} onChange={(event) => setTestRecipient(event.target.value)} placeholder="your.name@company.co.uk" /></label><button className="button secondary" disabled={testBusy || !testRecipient} onClick={() => void sendTest()}><Send /> {testBusy ? "Sending…" : "Send test"}</button></div>
        </article>
        <article className="panel system-section">
          <div className="panel-heading"><div><p className="eyebrow">MANUAL PROCESSING</p><h2>Run notifications now</h2><p>Evaluate current assignments and retry outstanding deliveries immediately.</p></div><RefreshCw /></div>
          <button className="button secondary" disabled={runBusy || !settings?.enabled} onClick={() => void runNow()}><BellRing /> {runBusy ? "Processing…" : "Run notification cycle"}</button>
        </article>
      </section>

      <section className="panel system-section">
        <div className="panel-heading"><div><p className="eyebrow">DELIVERY REGISTER</p><h2>Recent notification history</h2><p>Sent and failed emails are retained with their recipient, subject, attempts and timestamps.</p></div></div>
        {!deliveries.length ? <EmptyState title="No email deliveries" detail="Test or automatic notifications will appear here." /> : <div className="table-wrap notification-history"><table><thead><tr><th>Type</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Sent / next attempt</th></tr></thead><tbody>{deliveries.map((delivery) => <tr key={delivery.id}><td><strong>{deliveryLabel(delivery.notification_type)}</strong><small>{formatDate(delivery.created_at, true)}</small></td><td>{delivery.recipient_email}</td><td>{delivery.subject}{delivery.error_message && <small className="delivery-error"><AlertTriangle /> {delivery.error_message}</small>}</td><td><span className={statusClass(delivery.status)}>{delivery.status}</span></td><td>{delivery.attempt_count}</td><td>{delivery.sent_at ? formatDate(delivery.sent_at, true) : formatDate(delivery.scheduled_for, true)}</td></tr>)}</tbody></table></div>}
      </section>
    </main>
  );
}

function caughtMessage(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}
