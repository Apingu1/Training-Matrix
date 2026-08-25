import { useEffect, useState } from "react";
import { FileText, Folder, FolderOpen, MoveUp } from "lucide-react";
import { api, formatDate } from "../api";
import { ErrorBanner, LoadingBlock, Modal } from "./Common";

type BrowserItem = { name: string; path: string; type: "directory" | "file"; extension?: string; size?: number; modified_at?: string };
type BrowseResult = { path: string; parent?: string | null; items: BrowserItem[] };

export default function SourceBrowser({ onSelect, onClose }: { onSelect: (path: string) => void; onClose: () => void }) {
  const [path, setPath] = useState("");
  const [result, setResult] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    setLoading(true);
    setError("");
    api<BrowseResult>(`/documents/source/browse?path=${encodeURIComponent(path)}`)
      .then(setResult)
      .catch((caught) => setError(caught.message))
      .finally(() => setLoading(false));
  }, [path]);
  return (
    <Modal title="Browse controlled-document source" onClose={onClose} wide>
      <div className="source-path"><FolderOpen /><span>/controlled-documents/{result?.path}</span></div>
      <p className="form-hint">Only PDF and DOCX files inside the configured read-only server folder are shown.</p>
      <ErrorBanner error={error} />
      {loading ? <LoadingBlock /> : <div className="source-browser">
        {result?.parent !== null && result?.parent !== undefined && <button onClick={() => setPath(result.parent ?? "")}><MoveUp /><span>Parent folder</span></button>}
        {result?.items.map((item) => item.type === "directory" ? (
          <button key={item.path} onClick={() => setPath(item.path)}><Folder /><span>{item.name}</span><small>Folder</small></button>
        ) : (
          <button key={item.path} onClick={() => onSelect(item.path)}><FileText /><span>{item.name}</span><small>{item.extension?.slice(1).toUpperCase()} · {item.size ? `${Math.ceil(item.size / 1024)} KB` : ""} · {formatDate(item.modified_at)}</small></button>
        ))}
      </div>}
    </Modal>
  );
}
