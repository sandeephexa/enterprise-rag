# File uploads: implementation and testing

Implemented in the backend and frontend under `/Users/sandeepkumarboda/projects/enterprise-rag`.

## Run the updated app

The new Python dependencies are installed in the project's `.venv`. Restart any already-running backend to load the new routes. From the backend terminal, press Ctrl+C, then:

```bash
cd /Users/sandeepkumarboda/projects/enterprise-rag
uv sync --frozen --extra neural --extra dev
.venv/bin/uvicorn rag.app:app --host 127.0.0.1 --port 8000
```

Restart the frontend as well so Vite reloads the updated proxy timeout:

```bash
cd /Users/sandeepkumarboda/projects/enterprise-rag/frontend
npm ci
npm run dev -- --port 5174
```

Keep your existing backend `.env`, live-mode configuration, access keys and database. The update does not replace them. No new model API key is required for extraction. Your configured embedding model is reused in live mode; demo mode still uses its explicitly labelled demo encoder/generator.

Open `http://127.0.0.1:5174/`, connect with your backend access token, and select **Documents → File upload**. Choose your resume PDF, set access groups to `staff` (or the groups granted to your token), and click **Upload / retry pending files**. You do not need to fill in a source URI: it is generated automatically. Wait for **Indexed … chunks**, then query the resume in Playground and inspect the returned evidence. A scanned/image-only PDF requires OCR before uploading.

If the upload tab says the route is unavailable, restart the backend from the path above. `GET /ingest/formats` should return a JSON list of supported extensions, not 404.

## 1. Frontend changes

- `frontend/src/components/FileUploadPanel.tsx`: drag/drop plus keyboard-accessible file picker, queue of up to 20 files, filename/size preview, optional document IDs, access groups, validation messages, warnings, per-file status and retry/cancel controls.
- `frontend/src/components/IngestionPanel.tsx`: File upload, Paste text and JSON batch tabs; the existing text/JSON flow remains available.
- `frontend/src/api/client.ts`: authenticated multipart XHR client. Byte progress is real upload progress. At 100%, the UI switches to **Parsing and indexing…**; it declares success only after the server commits and returns a valid response.
- `frontend/src/api/uploads.ts`: response schemas, server capabilities and client validation. The backend independently validates every upload.
- Styles inherit the workbench's light/dark colors. Errors and filenames are rendered as text, never injected HTML.
- `VITE_API_BASE_URL` still configures the API base (default `/api`); `API_PROXY_TARGET` configures the Vite proxy (default `http://127.0.0.1:8000`). Proxy timeout is 195 seconds, client timeout 190 seconds.
- Multiple files are uploaded sequentially. One failed file does not block subsequent files or erase successful files. Retry processes only pending/failed valid files. Cancel aborts the active browser request and stops the queue; server work may already have completed.

## 2. Backend and parsing pipeline

**GET `/ingest/formats`** returns public, non-secret capabilities and configured limits.

**POST `/ingest/file`** accepts one multipart file per request. Requires an existing bearer identity with the `ingest` role. Fields:

- `file`: required binary file, with its original filename.
- `groups`: optional JSON string array, defaulting to the authenticated identity's groups. Every requested group must be authorized.
- `document_id`: optional stable ID, 1–100 letters/numbers/dots/underscores/hyphens.
- `title`: optional title, up to 200 characters, otherwise derived from the filename.

No tenant or source field is accepted. Tenant comes from the bearer identity. Default document ID is `file-` plus a filename hash; source is `urn:upload:` plus a filename hash. Reuploading the same filename into the same tenant replaces that document. Use distinct custom IDs to preserve revisions or distinguish equally named files from different folders.

Example request (read `RAG_TOKEN` from your own shell/secret manager; do not hard-code it):

```bash
curl --fail-with-body http://127.0.0.1:8000/ingest/file \
  -H "Authorization: Bearer $RAG_TOKEN" \
  -F 'file=@examples/uploads/support-policy.pdf' \
  -F 'groups=["staff"]' \
  -F 'document_id=upload-support-policy'
```

Example response:

```json
{
  "document_id": "upload-support-policy",
  "source": "urn:upload:<filename-sha256>",
  "indexed_chunks": 1,
  "extracted_characters": 211,
  "warnings": ["PDF table extraction is best effort; table content may also appear in page text."]
}
```

The raw JSON `POST /ingest` route is unchanged.

Parsing implementations in `rag/file_parser.py`:

- **PDF:** pdfplumber extracts selectable page text and detected table rows using font-relative word-gap detection, so small-font PDFs do not lose spaces between words. Text carries page labels; tables carry page/table/row labels. Table extraction is best effort and can duplicate page text. No OCR. Empty pages produce warnings; an entirely unreadable document is rejected. Password-protected PDFs are rejected.
- **DOCX:** entity-safe XML parsing of the ZIP package. Body paragraphs and tables retain reading order; table rows preserve cells as JSON arrays. Headers, footers and images are not indexed. Embedded objects are not executed or fetched.
- **XLSX:** openpyxl read-only loading, all sheets including hidden sheets, with sheet/row labels. Cells use cached values; formulas are never executed. Missing formula caches produce explicit placeholders and warnings. Recalculate/save in Excel to supply cached values.
- **CSV:** UTF decoding, delimiter detection (comma, semicolon, tab or pipe), strict CSV parsing and labelled rows preserving cell boundaries. Quoted fields and multiline values are supported. Header rows remain part of the text.
- **MD/TXT:** UTF-8 (optional BOM) or UTF-16 with BOM. Paragraphs and Markdown source remain text. HTML, links and commands are not executed.

`rag/uploads.py` owns multipart metadata validation, a private temporary directory and a disposable parser subprocess. The subprocess inherits no application credentials. Parsing has a killable deadline; the worker is terminated/reaped before temporary files are removed. This is process isolation and bounded input handling, not a complete operating-system security sandbox. For untrusted internet-facing workloads, run the service under the deployment's existing container resource and network restrictions.

## 3. End-to-end data flow

1. Browser fetches server limits and validates selected filenames, extensions and byte sizes.
2. Browser sends a `FormData` payload with bearer authorization. It lets the browser generate the multipart boundary.
3. ASGI ingress bounds raw request bytes, read time and concurrent upload requests. FastAPI verifies identity, role and ingestion admission slots.
4. Multipart parsing bounds file/metadata counts and metadata field sizes. Server validates the filename, extension, groups and document metadata.
5. The binary is copied into a private temporary directory under a neutral filename. A separate process validates and extracts text within configured limits. Raw binary files are never persisted in the index.
6. Extracted text becomes the existing `Document` schema with authorized groups, stable ID/title and generated source URI. Source markers travel as text into the chunks.
7. `HybridStore.ingest` runs the existing content guardrails and configured paragraph/sentence/semantic chunker. It checks each source slice against the live embedding tokenizer (including special tokens), splitting token-dense text and omitting overlap when necessary to stay within the model limit. Exact source offsets are retained. It creates all embeddings before modifying the database.
8. One SQLite transaction replaces that document's chunks and saves their source payloads, vector bytes and BM25 lexical tokens. A database error rolls back the replacement.
9. The response returns committed chunk count, character count, stable ID/source and extraction warnings. UI marks that file indexed.
10. `/query` uses the same authorized hybrid retrieval, reranking, generation and guardrails as pasted text. Citations point to exact offsets in **extracted text**, with page/sheet labels where available; they are not byte offsets into the original binary and do not download the original file.

Telemetry includes `ingest.parse` and `ingest.index` spans plus existing request IDs, status and request latency. Parse spans contain only format and character count; no document text, filenames or credentials are logged.

## 4. Limits, failures and cleanup

Defaults:

- 10 MiB per file: `RAG_MAX_UPLOAD_BYTES=10485760`; raw multipart allowance adds 64 KiB for boundaries/metadata.
- 200,000 extracted characters: `RAG_MAX_EXTRACTED_CHARS=200000`; maximum matches the Document schema.
- 30-second parse deadline: `RAG_UPLOAD_PARSE_TIMEOUT_S=30` (configurable up to 60).
- Two concurrent upload requests: `RAG_MAX_CONCURRENT_UPLOADS=2`.
- 100 PDF pages; 50 Excel sheets; 10,000 rows per sheet/CSV; 200 columns; 100,000 workbook/CSV cells.
- Office ZIP: at most 2,000 entries and 40 MiB total declared expansion; excessive compression ratios, encrypted entries, macros and XML DTD/entity payloads are rejected. ZIP contents are read without extracting member paths.
- Existing JSON route retains its 1 MB body limit. File uploads have their own limit.

Error responses have a safe `detail.code` and `detail.message` for parser/metadata failures. Generic middleware, auth and index errors retain the existing API contract.

- **413:** file, extracted text, page/table or Office archive expansion limit exceeded. Split the document; no silent truncation.
- **415:** unsupported extension or non-multipart request. MIME type alone is not trusted; binary format parsers validate file contents.
- **422:** empty/unreadable, invalid encoding, corrupted/encrypted files or invalid metadata.
- **400:** malformed multipart or content safety rejection.
- **401/403:** missing credentials, wrong role or unauthorized groups.
- **408:** upload-body or parsing deadline exceeded.
- **429/503:** rate limit, capacity/admission overload or unavailable indexing dependency.

Parse/validation/embedding failure occurs before replacement, so existing chunks remain. Transaction failures roll back both deletion and insertion. Each selected file has its own transaction: successful earlier files remain indexed if a later file fails. Multipart spools and private parsing directories are closed/removed on success, parser failure and parser cancellation/timeout.

The existing indexing worker runs in a thread with a 120-second response deadline. A network disconnect, client cancellation or indexing timeout can leave the commit outcome unknown to the browser; it cannot safely undo a commit already completed. Retry with the same document ID for an idempotent replacement. A parser failure never starts indexing. Process crashes can leave temporary files for the operating system's temporary-directory cleanup; operators can remove stale `rag-upload-*` directories when no workers are active.

## Verification and sample data

Synthetic examples for all six formats are in `examples/uploads/`. They contain a support-hours policy, not private resume data. The PDF includes a ruled table, DOCX includes a table, XLSX has two sheets and an intentionally uncached formula to demonstrate the warning.

```bash
.venv/bin/pytest -q
.venv/bin/ruff check rag tests
cd frontend
npm test
npm run build
```

Tests exercise real multipart payloads and real parser subprocesses, indexing and cited queries for every format; wrong extensions, corruption, encoding, empty inputs, bounds, authorization, duplicate multipart files, streamed oversized bodies, deterministic replacement IDs, parser deadline/cleanup, ZIP/XML protections, embedding failure and transactional rollback. Frontend tests cover multipart construction, auth, upload progress, response contracts, parsing errors, cancellation and preflight validation.

Browser verification uses an isolated demo backend/database, not your live resume index: upload all six examples, see **6 of 6 files indexed**, run **support available hours**, and observe a grounded response, six retrieved contexts and a citation. This verifies the upload integration; it does not certify live-model answer quality or change existing human-review decisions.

## Token-dense PDF regression

Character length does not predict token length. In a real 8,600-character PDF, one 700-character chunk produced 268 tokens against a 256-token embedding limit. The chunker now bounds initial units, packed chunks and optional overlap using the actual embedding tokenizer, including semantic-splitting inputs. It preserves source slices and does not silently truncate evidence. The PDF passed the multipart upload route with the real local model: HTTP 200, 15 chunks, largest chunk 256 tokens, 384-dimensional vectors. Testing used a temporary database without external LLM calls; the original file and live index were not changed. Restart the backend to load the fix, then retry the same document ID.

## Factual-answer verification improvements

After restarting the backend, re-upload PDFs ingested before the font-relative spacing fix, using the same document ID to replace their old chunks. This restores word boundaries in affected PDFs and can improve retrieval and evidence verification.

Short quotes that omit a subject, table header or unit can be verified against their already-cited full passage. A successful contextual check expands the returned citation to the exact passage used; uncited passages cannot rescue a claim, and invalid quotes still fail. One model correction attempt can repair an unsupported claim or invalid citation, within the existing guard deadline/cost allowance. The corrected draft must pass all the same guard checks. Medical insurance premium/coverage lookups no longer trigger review merely because of the word medical; requests for diagnosis, treatment or recommendations still retain the review policy.

The added stage is `answer_repair`. Provider failure, unresolved contradictions and unsupported facts may still require review. These changes do not lower entailment thresholds or guarantee all answers pass.
