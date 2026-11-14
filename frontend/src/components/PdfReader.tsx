import React, { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfjsWorker from "pdfjs-dist/build/pdf.worker.min.js?url";

// Set worker source
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker;

interface PdfReaderProps {
  fileData: ArrayBuffer | Uint8Array;
  onPageChange?: (currentPage: number, totalPages: number) => void;
  initialPage?: number;
}

export const PdfReader: React.FC<PdfReaderProps> = ({
  fileData,
  onPageChange,
  initialPage = 1,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [pdfDoc, setPdfDoc] = useState<any>(null);
  const [currentPage, setCurrentPage] = useState<number>(initialPage);
  const [numPages, setNumPages] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.25);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const renderTaskRef = useRef<any>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjsLib.getDocument({
      data: fileData,
      cMapUrl: "https://unpkg.com/pdfjs-dist@3.11.174/cmaps/",
      cMapPacked: true,
    });

    loadingTask.promise
      .then((doc) => {
        if (!active) return;
        setPdfDoc(doc);
        setNumPages(doc.numPages);
        setCurrentPage(1);
        setLoading(false);
        if (onPageChange) {
          onPageChange(1, doc.numPages);
        }
      })
      .catch((err) => {
        if (!active) return;
        console.error("PDF loading error:", err);
        setError("Failed to load PDF document.");
        setLoading(false);
      });

    return () => {
      active = false;
      loadingTask.destroy();
    };
  }, [fileData]);

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    let isCancelled = false;

    if (renderTaskRef.current) {
      renderTaskRef.current.cancel();
      renderTaskRef.current = null;
    }

    pdfDoc
      .getPage(currentPage)
      .then((page: any) => {
        if (isCancelled) return;

        const canvas = canvasRef.current;
        if (!canvas) return;
        const context = canvas.getContext("2d");
        if (!context) return;

        const viewport = page.getViewport({ scale });
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const renderContext = {
          canvasContext: context,
          viewport: viewport,
        };

        const renderTask = page.render(renderContext);
        renderTaskRef.current = renderTask;

        renderTask.promise
          .then(() => {
            renderTaskRef.current = null;
          })
          .catch((err: any) => {
            if (err?.name !== "RenderingCancelledException") {
              console.error("Page render error:", err);
            }
          });
      })
      .catch((err: any) => {
        console.error("Failed to load page:", err);
      });

    return () => {
      isCancelled = true;
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
        renderTaskRef.current = null;
      }
    };
  }, [pdfDoc, currentPage, scale]);

  const changePage = (newPage: number) => {
    if (newPage < 1 || newPage > numPages) return;
    setCurrentPage(newPage);
    if (onPageChange) {
      onPageChange(newPage, numPages);
    }
  };

  const pageBtn = (label: string, onClick: () => void, disabled: boolean) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="btn btn-ghost"
      style={{ padding: "0.3rem 0.6rem", fontSize: "0.82rem" }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div className="pdf-toolbar">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {pageBtn("◀ Prev", () => changePage(currentPage - 1), currentPage <= 1 || loading)}
          <span className="page-info">
            Page <strong style={{ color: "var(--color-text)" }}>{currentPage}</strong> of <strong style={{ color: "var(--color-text)" }}>{numPages}</strong>
          </span>
          {pageBtn("Next ▶", () => changePage(currentPage + 1), currentPage >= numPages || loading)}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {pageBtn("−", () => setScale((s) => Math.max(0.75, s - 0.2)), false)}
          <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", minWidth: 44, textAlign: "center" }}>
            {Math.round(scale * 100)}%
          </span>
          {pageBtn("+", () => setScale((s) => Math.min(2.5, s + 0.2)), false)}
          {pageBtn("Reset", () => setScale(1.25), false)}
        </div>
      </div>

      <div className="pdf-viewport">
        {loading && (
          <div style={{ color: "var(--color-text-muted)", marginTop: "4rem", textAlign: "center" }}>
            <p>📄 Loading PDF Document...</p>
          </div>
        )}
        {error && (
          <div className="banner banner-warning" style={{ marginTop: "4rem" }}>
            ⚠️ {error}
          </div>
        )}
        <canvas
          ref={canvasRef}
          style={{
            display: loading || error ? "none" : "block",
            background: "#fff",
            maxWidth: "100%",
          }}
        />
      </div>
    </div>
  );
};
