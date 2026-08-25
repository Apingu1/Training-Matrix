import { useEffect, useState } from "react";
import { AlertTriangle, BookOpenCheck, CheckCircle2, Clock3, FileText, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatDate, statusClass } from "../api";
import { ErrorBanner, PageHeader } from "../components/Common";
import { useAuth } from "../hooks/useAuth";
import type { ControlledDocument, TrainingAssignment } from "../types";

type Stats = { assigned: number; overdue: number; completed: number; due_within_7_days: number; total: number };
type Compliance = { user_id: number; display_name: string; open: number; overdue: number; completed: number; compliance_percent: number };

export default function DashboardPage() {
  const { me, has } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [assignments, setAssignments] = useState<TrainingAssignment[]>([]);
  const [documents, setDocuments] = useState<ControlledDocument[]>([]);
  const [compliance, setCompliance] = useState<Compliance[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const requests: Promise<unknown>[] = [];
    if (has("training.view_own")) {
      requests.push(api<Stats>("/training/dashboard").then(setStats));
      requests.push(api<TrainingAssignment[]>("/training/my-assignments?status=ASSIGNED").then(setAssignments));
    }
    if (has("documents.view")) requests.push(api<ControlledDocument[]>("/documents").then(setDocuments));
    if (has("training.view_team")) requests.push(api<Compliance[]>("/training/compliance-summary").then(setCompliance));
    Promise.all(requests).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load dashboard"));
  }, [has]);

  const dueSoon = assignments.filter((item) => new Date(item.due_at).valueOf() <= Date.now() + 7 * 86_400_000).slice(0, 5);
  const reviewsDue = documents.filter((item) => item.current_version?.review_due_date && new Date(item.current_version.review_due_date).valueOf() <= Date.now() + 90 * 86_400_000).slice(0, 5);
  const teamRisks = compliance.filter((item) => item.overdue > 0).sort((a, b) => b.overdue - a.overdue).slice(0, 5);
  return (
    <main className="page">
      <PageHeader eyebrow="COMPLIANCE OVERVIEW" title={`Good ${new Date().getHours() < 12 ? "morning" : "afternoon"}, ${me?.display_name.split(" ")[0]}`} description="Your controlled-document and training position at a glance." />
      <ErrorBanner error={error} />
      <section className="metric-grid">
        <article className="metric-card"><span className="metric-icon green"><BookOpenCheck /></span><div><p>Open training</p><strong>{stats?.assigned ?? 0}</strong><span>Assigned and in date</span></div></article>
        <article className="metric-card"><span className="metric-icon red"><AlertTriangle /></span><div><p>Overdue</p><strong>{stats?.overdue ?? 0}</strong><span>Requires attention</span></div></article>
        <article className="metric-card"><span className="metric-icon gold"><Clock3 /></span><div><p>Due in 7 days</p><strong>{stats?.due_within_7_days ?? 0}</strong><span>Upcoming commitments</span></div></article>
        <article className="metric-card"><span className="metric-icon blue"><CheckCircle2 /></span><div><p>Completed</p><strong>{stats?.completed ?? 0}</strong><span>Version-specific evidence</span></div></article>
      </section>
      <section className="dashboard-grid">
        <article className="panel span-2">
          <div className="panel-heading"><div><p className="eyebrow">MY PRIORITIES</p><h2>Training due soon</h2></div><Link to="/training">View all</Link></div>
          {dueSoon.length ? <div className="priority-list">{dueSoon.map((item) => <div key={item.id}><span className="doc-type">{item.document_type}</span><div><strong>{item.document_code} · {item.version_label}</strong><p>{item.document_title}</p></div><div className="priority-date"><span className={statusClass(item.status)}>{item.status}</span><small>{formatDate(item.due_at)}</small></div></div>)}</div> : <div className="success-state"><CheckCircle2 /><div><strong>You are up to date</strong><p>No training is due within the next seven days.</p></div></div>}
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">DOCUMENT CONTROL</p><h2>Review horizon</h2></div><FileText /></div>
          {reviewsDue.length ? <div className="compact-list">{reviewsDue.map((item) => <div key={item.id}><span>{item.code}</span><strong>{formatDate(item.current_version?.review_due_date)}</strong></div>)}</div> : <p className="muted">No current documents are due for review within 90 days.</p>}
        </article>
        {has("training.view_team") && <article className="panel span-3">
          <div className="panel-heading"><div><p className="eyebrow">TEAM OVERSIGHT</p><h2>Compliance attention</h2></div><UsersRound /></div>
          {teamRisks.length ? <div className="team-risk-grid">{teamRisks.map((item) => <div key={item.user_id}><div className="avatar small">{item.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</div><div><strong>{item.display_name}</strong><span>{item.compliance_percent}% compliant</span></div><span className="status status-overdue">{item.overdue} overdue</span></div>)}</div> : <div className="success-state"><CheckCircle2 /><div><strong>No overdue team training</strong><p>All active users are within their assigned due dates.</p></div></div>}
        </article>}
      </section>
    </main>
  );
}
