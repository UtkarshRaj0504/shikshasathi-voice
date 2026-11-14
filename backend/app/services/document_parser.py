"""
Document text extraction utility supporting PDF, DOCX, and TXT.
"""

import os
import fitz  # PyMuPDF
from docx import Document as DocxDocument


def extract_text(file_path: str, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT based on file extension."""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)

    elif ext == ".docx":
        doc = DocxDocument(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    elif ext in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    else:
        raise ValueError(f"Unsupported file format: {ext}")
