import { useEffect, useState, type FormEvent } from "react";
import { CheckCircle2, ChevronDown, FileCheck2, ShieldAlert, X } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { api, apiBlob } from "../api";
import { useAuth } from "../hooks/useAuth";
import type { DocumentVersion, TrainingAssignment } from "../types";
import { ErrorBanner, LoadingBlock } from "./Common";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

function PdfPage({ pdf, pageNumber, watermark }: { pdf: PDFDocumentProxy; pageNumber: number; watermark: string }) {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!canvas) return;
    let cancelled = false;
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | undefined;
    void pdf.getPage(pageNumber).then((page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale: 1.35 });
      const context = canvas.getContext("2d");
      if (!context) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      renderTask = page.render({ canvasContext: context, viewport });
      return renderTask.promise;
    }).catch(() => undefined);
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [canvas, pageNumber, pdf]);
  return (
    <div className="pdf-page">
      <canvas ref={setCanvas} />
      <span className="pdf-watermark">{watermark}</span>
      <span className="pdf-page-number">Page {pageNumber}</span>
    </div>
  );
}

type ViewerProps = {
  version: DocumentVersion;
  code: string;
  title: string;
  assignment?: TrainingAssignment | null;
  onClose: () => void;
  onCompleted?: () => void;
};

export default function DocumentViewer({ version, code, title, assignment, onClose, onCompleted }: ViewerProps) {
  const { me } = useAuth();
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [showAttestation, setShowAttestation] = useState(false);
  const [signing, setSigning] = useState(false);
  const [statement, setStatement] = useState("I confirm that I have read and understood this document and will comply with its requirements.");

  useEffect(() => {
    if (!assignment) return;
    api<{ statement: string }>("/training/acknowledgement-statement").then((result) => setStatement(result.statement)).catch(() => undefined);
  }, [assignment]);

  useEffect(() => {
    let disposed = false;
    let loaded: PDFDocumentProxy | null = null;
    setLoading(true);
    setError("");
    apiBlob(`/document-versions/${version.id}/view`)
      .then((blob) => blob.arrayBuffer())
      .then((data) => pdfjs.getDocument({ data }).promise)
      .then((document) => {
        loaded = document;
        if (!disposed) setPdf(document);
      })
      .catch((caught) => !disposed && setError(caught instanceof Error ? caught.message : "Unable to open document"))
      .finally(() => !disposed && setLoading(false));
    return () => {
      disposed = true;
      void loaded?.destroy();
    };
  }, [version.id]);

  const acknowledge = async (event: FormEvent) => {
    event.preventDefault();
    if (!assignment) return;
    setSigning(true);
    setError("");
    try {
      await api(`/training/assignments/${assignment.id}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({ password, statement }),
      });
      onCompleted?.();
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Acknowledgement failed");
    } finally {
      setSigning(false);
    }
  };

  const watermark = `${me?.display_name ?? "Authorised user"} • ${new Date().toLocaleDateString("en-GB")}`;
  return (
    <div className="viewer-shell" role="dialog" aria-modal="true">
      <header className="viewer-header">
        <div><p className="eyebrow light">CONTROLLED VIEW</p><h2>{code} · {version.version_label}</h2><span>{title}</span></div>
        <div className="viewer-integrity"><FileCheck2 size={18} /><span>SHA-256 verified</span></div>
        <button className="icon-button inverse" onClick={onClose} aria-label="Close viewer"><X /></button>
      </header>
      <div className="viewer-notice"><ShieldAlert size={17} /> Uncontrolled screenshots or reproductions are not authorised. Always use the current effective version shown in this system.</div>
      <section className="viewer-body">
        {loading && <LoadingBlock label="Verifying and rendering controlled document…" />}
        <ErrorBanner error={error} />
        {pdf && Array.from({ length: pdf.numPages }, (_, index) => <PdfPage key={index + 1} pdf={pdf} pageNumber={index + 1} watermark={watermark} />)}
      </section>
      {assignment?.stored_status === "ASSIGNED" && pdf && (
        <footer className={`attestation-drawer ${showAttestation ? "open" : ""}`}>
          <button className="attestation-toggle" onClick={() => setShowAttestation((value) => !value)}>
            <span><CheckCircle2 /> Ready to confirm you have read this version?</span><ChevronDown />
          </button>
          {showAttestation && (
            <form onSubmit={acknowledge}>
              <p>{statement}</p>
              <label>Password re-authentication<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
              <button className="button gold" disabled={signing}>{signing ? "Applying signature…" : "Sign read & understood"}</button>
            </form>
          )}
        </footer>
      )}
    </div>
  );
}
