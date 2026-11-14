"""
Lightweight markdown formatting helpers for tutor answers.

Two concerns, kept separate:

- ``normalize_answer_markdown`` tidies the raw LLM answer so it renders cleanly
  (markdown) in the student UI: consistent bullet markers, no heading markers or
  code fences, no trailing whitespace, no runs of blank lines.
- ``strip_markdown_for_speech`` turns the same text into something a TTS engine
  reads naturally: emphasis markers, link syntax, backticks and bullet markers
  are removed and list items become short sentences.

Both helpers are deliberately conservative: a lone ``*`` that is not part of a
markdown pair (for example the multiplication in "2 * 3") is preserved.
"""

import re

# A fenced code block delimiter line, e.g. ```python or ``` (leading indentation
# allowed). The trailing newline is consumed so no blank line is left behind.
_FENCE_LINE_RE = re.compile(r"^[ \t]*```[^\n]*\n?", re.MULTILINE)

# A markdown ATX heading marker at the start of a line, e.g. "## Title".
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE)

# A leading "* " bullet marker (asterisk bullets are normalised to "- ").
_STAR_BULLET_RE = re.compile(r"^([ \t]*)\*[ \t]+", re.MULTILINE)

# Trailing spaces/tabs at the end of a line.
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# Three or more blank lines collapse to a single blank line.
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Paired emphasis markers: only remove a marker run that wraps non-space content.
_BOLD_STAR_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_BOLD_UNDERSCORE_RE = re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![A-Za-z0-9_])_(?=\S)([^_]+?)(?<=\S)_(?![A-Za-z0-9_])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)

# Markdown images and links: keep the human-readable text only.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")

# Bullet / numbered-list markers at the start of a line.
_LIST_MARKER_RE = re.compile(r"^(?:[-*+][ \t]+|(\d+)[.)][ \t]+)(.*)$")

# Sentence-ending punctuation, including the Devanagari danda ("।").
_SENTENCE_ENDINGS = (".", "!", "?", "।", "\u2026")


def normalize_answer_markdown(text: str | None) -> str:
    """Tidy an answer for markdown rendering without changing its meaning.

    - "* " bullets become "- "
    - heading markers ("#", "##", ...) are removed
    - code fence lines (```) are removed
    - trailing spaces are trimmed and 3+ blank lines collapse to one
    """
    if not text:
        return text or ""

    result = _FENCE_LINE_RE.sub("", text)
    result = _HEADING_RE.sub("", result)
    result = _STAR_BULLET_RE.sub(r"\1- ", result)
    result = _TRAILING_SPACE_RE.sub("", result)
    result = _EXCESS_BLANK_LINES_RE.sub("\n\n", result)
    return result.strip()


def strip_markdown_for_speech(text: str | None) -> str:
    """Turn markdown into plain prose for TTS.

    Removes emphasis markers, backticks, heading markers, link syntax (keeping
    the link text) and list markers, converting each list item into a short
    sentence. Legitimate lone asterisks (e.g. "2 * 3") are preserved.
    """
    if not text:
        return text or ""

    result = text

    # Drop fenced-code delimiter lines but keep the code inside them.
    result = _FENCE_LINE_RE.sub("", result)

    # Images and links -> their visible text.
    result = _IMAGE_RE.sub(r"\1", result)
    result = _LINK_RE.sub(r"\1", result)

    # Headings lose their leading "#" markers.
    result = _HEADING_RE.sub("", result)

    # Equality / emphasis markers.
    result = _STRIKE_RE.sub(r"\1", result)
    result = _BOLD_STAR_RE.sub(r"\1", result)
    result = _BOLD_UNDERSCORE_RE.sub(r"\1", result)
    result = _ITALIC_STAR_RE.sub(r"\1", result)
    result = _ITALIC_UNDERSCORE_RE.sub(r"\1", result)

    # Inline-code backticks are dropped, the wrapped text is kept.
    result = result.replace("`", "")

    # Each line: strip list markers and make sure it ends like a sentence.
    spoken_lines = []
    for raw_line in result.split("\n"):
        line = raw_line.strip()
        marker = _LIST_MARKER_RE.match(line)
        if marker:
            line = marker.group(2).strip()
            if line and not line.endswith(_SENTENCE_ENDINGS):
                line += "."
        spoken_lines.append(line)

    result = "\n".join(spoken_lines)
    result = _EXCESS_BLANK_LINES_RE.sub("\n\n", result)
    return result.strip()
