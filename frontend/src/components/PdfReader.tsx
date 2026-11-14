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

  // Load PDF document from binary data
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

  // Render current page onto canvas
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    let isCancelled = false;

    // Cancel existing render task before starting a new one
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#495057", borderRadius: "8px", overflow: "hidden" }}>
      {/* Navigation & Controls Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.6rem 1rem",
          background: "#212529",
          color: "#fff",
          fontSize: "0.9rem",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => changePage(currentPage - 1)}
            disabled={currentPage <= 1 || loading}
            style={{
              padding: "0.35rem 0.75rem",
              background: currentPage <= 1 ? "#343a40" : "#0d6efd",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: currentPage <= 1 ? "not-allowed" : "pointer",
              fontWeight: 500,
            }}
          >
            ◀ Prev
          </button>
          <span>
            Page <strong>{currentPage}</strong> of <strong>{numPages}</strong>
          </span>
          <button
            onClick={() => changePage(currentPage + 1)}
            disabled={currentPage >= numPages || loading}
            style={{
              padding: "0.35rem 0.75rem",
              background: currentPage >= numPages ? "#343a40" : "#0d6efd",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: currentPage >= numPages ? "not-allowed" : "pointer",
              fontWeight: 500,
            }}
          >
            Next ▶
          </button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => setScale((s) => Math.max(0.75, s - 0.2))}
            style={{
              padding: "0.35rem 0.6rem",
              background: "#495057",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
            }}
            title="Zoom Out"
          >
            🔍 -
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button
            onClick={() => setScale((s) => Math.min(2.5, s + 0.2))}
            style={{
              padding: "0.35rem 0.6rem",
              background: "#495057",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
            }}
            title="Zoom In"
          >
            🔍 +
          </button>
          <button
            onClick={() => setScale(1.25)}
            style={{
              padding: "0.35rem 0.6rem",
              background: "#495057",
              color: "#ced4da",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.8rem",
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Canvas Display Viewport */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          display: "flex",
          justifyContent: "center",
          alignItems: "flex-start",
          padding: "1rem",
        }}
      >
        {loading && (
          <div style={{ color: "#fff", marginTop: "4rem", textAlign: "center" }}>
            <p>📄 Loading PDF Document...</p>
          </div>
        )}
        {error && (
          <div style={{ color: "#ffc107", marginTop: "4rem", textAlign: "center" }}>
            <p>⚠️ {error}</p>
          </div>
        )}
        <canvas
          ref={canvasRef}
          style={{
            display: loading || error ? "none" : "block",
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
            background: "#fff",
            maxWidth: "100%",
          }}
        />
      </div>
    </div>
  );
};
