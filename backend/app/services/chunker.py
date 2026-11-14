"""
Text chunking utility: splits text into ~500-token chunks with ~50-token overlap.
Approximates tokens as ~4 characters per token (or word-based slicing).
"""

def chunk_text(text: str, chunk_size_chars: int = 2000, overlap_chars: int = 200) -> list[str]:
    """Split text into overlapping chunks."""
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= chunk_size_chars:
        return [text]

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size_chars
        if end < text_len:
            # Try to find a natural boundary (newline or period)
            boundary = max(
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
                text.rfind(" ", start, end)
            )
            if boundary > start + chunk_size_chars // 2:
                end = boundary + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap_chars
        if start < 0:
            start = 0
        if end >= text_len:
            break

    return chunks
