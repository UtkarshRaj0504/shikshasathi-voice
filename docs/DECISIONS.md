# Architectural & Design Decisions

## 1. Document Chunk Page Attribution & Current-Page Boosting

* **Context**: When reading long educational PDFs, student queries are frequently related to the active page currently in view in the reader.
* **Decision**: We added an optional `page_number` column (integer) to `DocumentChunk`. During document processing (`process_document`), PyMuPDF parses the document page-by-page via `extract_document_pages`, attributing each chunk to its corresponding 1-indexed PDF page.
* **Query Boosting**: `/ask` accepts an optional `current_page: int | None` parameter. When present, chunks originating from `current_page` receive a relevance score boost (+0.2), elevating chunks from the active page in the reader without suppressing strong global matches.

## 2. Document & Chapter Student Visibility ("Published" State)

* **Context**: Students must only have access to fully processed, ready materials and chapters that contain actual study content.
* **Decision**: Rather than introducing a redundant "published" toggle, all documents with `status == "ready"` are treated as visible.
* **Enforcement**:
  - `GET /subjects/{id}/chapters` filters chapters for student users so only chapters having at least one `status == "ready"` document are returned.
  - `GET /documents/{id}/file` permits students to stream only documents with `status == "ready"`. Any attempt to access "pending", "processing", or "failed" documents returns HTTP 403 Forbidden.
  - Teachers retain full access to all of their own documents across all processing states.

## 3. Teacher Voice Cloning Consent & Security

* **Context**: Voice cloning must be strictly consensual, transparent, and legally sound.
* **Decision**:
  - `VoiceProfile` records have two gates: `status == "active"` and `consent_confirmed == True`.
  - Student preference selection (`PUT /me/preferences`) strictly validates that any assigned `voice_profile_id` belongs to an active profile with confirmed consent; otherwise returning HTTP 400 Bad Request.
  - `GET /voices` lists only active profiles with confirmed consent.
  - Every playback generated using a cloned voice displays the mandatory transparency disclaimer:
    `"AI-generated voice, authorized by the teacher."`

## 4. TTS Fallback Architecture

* **Context**: External cloned voice synthesis APIs may experience rate limits, latency, or outages. A student studying should not be blocked from hearing answers.
* **Decision**:
  - If a teacher's cloned voice fails or is invalid, the backend automatically falls back to the default synthetic voice.
  - The API response signals `fallback = True` with a clear user notice (`"Teacher voice unavailable; used default voice."`).
