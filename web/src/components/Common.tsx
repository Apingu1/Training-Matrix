import type { ReactNode } from "react";
import { Inbox, X } from "lucide-react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><Inbox size={34} /><h3>{title}</h3><p>{detail}</p></div>;
}

export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className={`modal-card ${wide ? "wide" : ""}`}>
        <div className="modal-header"><h2>{title}</h2><button className="icon-button" onClick={onClose}><X /></button></div>
        {children}
      </div>
    </div>
  );
}

export function ErrorBanner({ error }: { error: string }) {
  return error ? <div className="alert error">{error}</div> : null;
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return <div className="loading-block"><span className="spinner" />{label}</div>;
}
