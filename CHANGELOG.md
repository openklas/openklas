# Changelog

## [Unreleased]

### feat: client audio recording → transcribe → summarize pipeline

Added two new endpoints that accept a browser-recorded audio file, transcribe it with Groq Whisper (Korean), summarize with Claude, and save to Obsidian — reusing the existing summarize/save pipeline from `summarize_service.py`.

**New endpoints (under `/api/recorded-lectures`):**
- `POST /record` — upload audio (`UploadFile`, any format Groq supports: webm, ogg, mp3, wav, m4a), pass `subject_code` + `lecture_title` (and optionally `week_no`). Looks up course title from KLAS timetable, runs pipeline in background. Supports `force=true` to override a stuck job.
- `GET /record/status` — poll pipeline progress. `step` values: `transcribing | summarizing | saving | done | error`. Returns transcript, summary, and Obsidian path on completion.

**Modified files:**
- `app/services/summarize_service.py` — added `_transcribe_audio_bytes`, `_run_record_pipeline`, `start_record_background`, `get_record_status`, `_record_status`; all reuse the existing `_summarize` and `save_to_obsidian` functions unchanged
- `app/schemas/recorded_lecture.py` — added `RecordJobResponse`, `RecordStatusResponse`
- `app/api/routes/recorded_lectures.py` — added `POST /record` and `GET /record/status` endpoints; added `File`, `UploadFile` imports

**Client usage:** record in the browser with `MediaRecorder` (produces WebM/Opus, natively supported by Groq), POST the blob to `/api/recorded-lectures/record`, poll `/record/status` until `step == "done"`.

---

### feat: per-user RAG service for lecture PDF materials

Added a full local RAG (Retrieval-Augmented Generation) pipeline scoped per user. PDFs are chunked semantically, embedded with a local sentence-transformer model, stored in pgvector, reranked with a cross-encoder, and answered by a local Ollama LLM — no external API calls required.

**New files:**
- `app/models/document.py` — `Document` and `DocumentChunk` SQLAlchemy models with `pgvector` `Vector(384)` column
- `app/services/embedding_service.py` — singleton wrapper around `sentence-transformers` (`BAAI/bge-small-en-v1.5`) for batch embedding and `cross-encoder/ms-marco-MiniLM-L-6-v2` for reranking
- `app/services/rag_service.py` — `ingest_pdf` (parse → semantic chunk → embed → store), `query_rag` (embed → cosine retrieve → rerank → Ollama generate), `delete_document`
- `app/schemas/rag.py` — Pydantic schemas for ingest/query request/response
- `app/api/routes/rag.py` — four endpoints under `/api/rag`
- `alembic/versions/f7a2b9c4d1e3_add_rag_documents.py` — migration: `CREATE EXTENSION vector`, `documents` table, `document_chunks` table with IVFFlat index

**Modified files:**
- `pyproject.toml` — added `sentence-transformers`, `pgvector`, `ollama`
- `alembic/env.py` — registered `app.models.document` for autogenerate
- `main.py` — mounted `/api/rag` router

**Endpoints:**
- `POST /api/rag/ingest` — upload PDF (multipart), optional `subject_code`
- `GET /api/rag/documents` — list user's ingested documents
- `DELETE /api/rag/documents/{id}` — delete document + all chunks
- `POST /api/rag/query` — `{ question, subject_code?, top_k? }` → `{ question, answer }`

**Architecture decisions:**
- Semantic chunking at paragraph/heading boundaries (no fixed token windows) with sentence-level overflow splitting for large paragraphs
- 20 candidates retrieved by cosine similarity, reranked to top-k (default 5) by cross-encoder
- Embedding model constant in `embedding_service.py` — swap to `paraphrase-multilingual-MiniLM-L12-v2` for Korean content
- Ollama model constant in `rag_service.py` — requires `ollama serve` and `ollama pull llama3.2` locally

### feat: recorded lecture video summarization pipeline

Added a full pipeline that downloads a KLAS recorded lecture, transcribes it, summarizes it with Claude, and saves the result to the Obsidian klas-user vault.

**New files:**
- `app/services/summarize_service.py` — core pipeline service

**Modified files:**
- `app/schemas/recorded_lecture.py` — added `SummarizeJobResponse`, `SummarizeStatusResponse`
- `app/api/routes/recorded_lectures.py` — added `POST /summarize` and `GET /summarize/status`
- `pyproject.toml` — added `faster-whisper>=1.0.0`

**Pipeline steps:**
1. Extract content code from `starting` URL (`/em/<code>`)
2. Launch Playwright, log into KLAS browser session to establish kwcommons.kw.ac.kr cookies
3. Try `screen.mp4` then `mobile/ssmovie.mp4` via `page.request.get()`
4. Save to temp file, transcribe with `faster-whisper` (small model, Korean, CPU int8)
5. Summarize with `claude-sonnet-4-6`
6. Write Markdown note to `Obsidian Vault/klas-user/semester/8/courses/<course>/lectures/W<n>-<title>.md`

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/recorded-lectures/summarize` | Start pipeline (background task) |
| GET | `/api/recorded-lectures/summarize/status` | Poll job progress and get results |

**Design notes:**
- Single in-memory `SummarizeStatus` instance (same pattern as watch service); only one job at a time
- Playwright reuses the same browser-login approach as the watch service to handle kwcommons auth
- `faster-whisper` import is deferred so the model loads only when transcription runs
- `force=true` query param overrides a stuck job
