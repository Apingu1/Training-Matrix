import { useEffect, useState } from "react";
import { BookOpen, CalendarClock, Search } from "lucide-react";
import { api, formatDate } from "../api";
import { EmptyState, ErrorBanner, PageHeader } from "../components/Common";
import DocumentViewer from "../components/DocumentViewer";
import type { ControlledDocument } from "../types";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<ControlledDocument[]>([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("ALL");
  const [selected, setSelected] = useState<ControlledDocument | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<ControlledDocument[]>("/documents").then(setDocuments).catch((caught) => setError(caught.message)); }, []);
  const types = ["ALL", ...Array.from(new Set(documents.map((item) => item.document_type))).sort()];
  const visible = documents.filter((item) => {
    const needle = search.toLowerCase();
    return item.current_version && (type === "ALL" || item.document_type === type) && (!needle || `${item.code} ${item.title}`.toLowerCase().includes(needle));
  });
  return (
    <main className="page">
      <PageHeader eyebrow="MASTER LIST" title="Controlled documents" description="The current effective version is presented by default. Superseded versions remain protected in document history." />
      <ErrorBanner error={error} />
      <div className="toolbar">
        <label className="search-box grow"><Search size={18} /><input placeholder="Search document number or title" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <select value={type} onChange={(event) => setType(event.target.value)}>{types.map((item) => <option key={item}>{item}</option>)}</select>
      </div>
      {visible.length ? <div className="document-list">{visible.map((item) => (
        <article key={item.id}>
          <div className="document-icon"><span>{item.document_type.slice(0, 3)}</span></div>
          <div className="document-main"><p className="doc-code">{item.code}</p><h3>{item.title}</h3><div className="document-tags"><span>{item.owner_department}</span><span>Version {item.current_version?.version_label}</span><span>Effective {formatDate(item.current_version?.effective_at)}</span></div></div>
          <div className="document-review"><CalendarClock /><span>Review due</span><strong>{formatDate(item.current_version?.review_due_date)}</strong></div>
          <button className="button secondary" onClick={() => setSelected(item)}><BookOpen size={17} /> View</button>
        </article>
      ))}</div> : <EmptyState title="No controlled documents found" detail="Adjust the filters or ask Document Control to release the first effective version." />}
      {selected?.current_version && <DocumentViewer version={selected.current_version} code={selected.code} title={selected.title} onClose={() => setSelected(null)} />}
    </main>
  );
}
