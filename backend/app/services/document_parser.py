"""
Document text extraction utility supporting PDF, DOCX, and TXT.
Supports both flat text extraction and page-attributed extraction.
"""

import os
import fitz  # PyMuPDF
from docx import Document as DocxDocument


def extract_document_pages(file_path: str, filename: str) -> list[tuple[int | None, str]]:
    """
    Extract text as a list of (page_number, text) tuples.
    For PDF, page_number is 1-based.
    For DOCX/TXT/MD, page_number is 1.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        pages: list[tuple[int | None, str]] = []
        with fitz.open(file_path) as doc:
            for idx, page in enumerate(doc, start=1):
                text = page.get_text()
                if text.strip():
                    pages.append((idx, text))
        return pages

    elif ext == ".docx":
        doc = DocxDocument(file_path)
        full_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return [(1, full_text)] if full_text.strip() else []

    elif ext in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            full_text = f.read()
        return [(1, full_text)] if full_text.strip() else []

    else:
        raise ValueError(f"Unsupported file format: {ext}")


def extract_text(file_path: str, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT based on file extension."""
    pages = extract_document_pages(file_path, filename)
    return "\n".join(text for _, text in pages)
