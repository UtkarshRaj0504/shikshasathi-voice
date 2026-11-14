"""
Document text extraction utility supporting PDF, DOCX, and TXT.
Supports both flat text extraction and page-attributed extraction.
"""

import os
from io import BytesIO

import fitz  # PyMuPDF
from docx import Document as DocxDocument


def extract_document_pages(
    file_path: str | None,
    filename: str,
    file_data: bytes | None = None,
) -> list[tuple[int | None, str]]:
    """
    Extract text as a list of (page_number, text) tuples.
    For PDF, page_number is 1-based.
    For DOCX/TXT/MD, page_number is 1.
    """
    ext = os.path.splitext(filename)[1].lower()
    if file_data is None and not file_path:
        raise FileNotFoundError(f"No stored content for {filename}")

    if ext == ".pdf":
        pages: list[tuple[int | None, str]] = []
        source = (
            fitz.open(stream=file_data, filetype="pdf")
            if file_data is not None
            else fitz.open(file_path)
        )
        with source as doc:
            for idx, page in enumerate(doc, start=1):
                text = page.get_text()
                if text.strip():
                    pages.append((idx, text))
        return pages

    elif ext == ".docx":
        doc = DocxDocument(BytesIO(file_data)) if file_data is not None else DocxDocument(file_path)
        full_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return [(1, full_text)] if full_text.strip() else []

    elif ext in [".txt", ".md"]:
        if file_data is not None:
            full_text = file_data.decode("utf-8", errors="ignore")
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
        return [(1, full_text)] if full_text.strip() else []

    else:
        raise ValueError(f"Unsupported file format: {ext}")


def extract_text(
    file_path: str | None,
    filename: str,
    file_data: bytes | None = None,
) -> str:
    """Extract plain text from PDF, DOCX, or TXT based on file extension."""
    pages = extract_document_pages(file_path, filename, file_data=file_data)
    return "\n".join(text for _, text in pages)
