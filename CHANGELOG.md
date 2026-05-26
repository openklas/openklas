# Changelog

## [Unreleased]

### feat(homework): GET /api/homework/team-projects — team project list

New endpoint that fetches team project assignments from KLAS `PrjctStdList.do` for a given subject code. Returns project title, dates, submission status, team number, and team purpose, sorted most-recent first.

**Changed files:**
- `app/core/config.py` — added `KLAS_TEAM_PROJECT_URL` setting
- `.env` — added `KLAS_TEAM_PROJECT_URL=https://klas.kw.ac.kr/std/lis/evltn/PrjctStdList.do`
- `app/services/klas_service.py` — added `get_team_projects(subject_code, year, semester)` method
- `app/schemas/homework.py` — added `TeamProject` and `TeamProjectListResponse` schemas
- `app/api/routes/homework.py` — added `GET /team-projects` endpoint

### feat(lectures): GET /api/lectures/course/{subject_code} — course syllabus info

New endpoint that fetches course metadata from KLAS `LectrePlanData.do` for a given subject code and returns a clean summary: course name, type (e.g. 전선), credit count, professor name, and professor email.

**Changed files:**
- `app/core/config.py` — added `KLAS_COURSE_INFO_URL` setting
- `.env` — added `KLAS_COURSE_INFO_URL=https://klas.kw.ac.kr/std/cps/atnlc/LectrePlanData.do`
- `app/services/klas_service.py` — added `get_course_info(subject_code)` method
- `app/schemas/lecture.py` — added `CourseInfo` and `CourseInfoResponse` schemas
- `app/api/routes/lectures.py` — added `GET /course/{subject_code}` endpoint

### feat(oauth): OAuth 2.0 connector support for Claude.ai and AI assistants

Added a full OAuth 2.0 authorization server so users can connect KLAS to Claude.ai (and other AI assistants) via the "Add custom connector" dialog — no local setup required.

**New files:**
- `app/api/routes/oauth.py` — OAuth endpoints: `/.well-known/oauth-authorization-server`, `/oauth/register` (RFC 7591 dynamic client registration), `GET/POST /oauth/authorize` (HTML login form), `POST /oauth/token`
- `app/models/oauth.py` — `OAuthToken` DB model: stores long-lived access token + Fernet-encrypted KLAS credentials per student
- `app/core/encryption.py` — Fernet encryption utility; uses `OAUTH_ENCRYPTION_KEY` (falls back to `SESSION_ENCRYPTION_KEY`)
- `alembic/versions/b1c2d3e4f5a6_add_oauth_tokens.py` — migration for `oauth_tokens` table

**Modified files:**
- `app/core/config.py` — added `OAUTH_ENCRYPTION_KEY` setting
- `app/api/deps.py` — `get_current_user_from_klas_session` now accepts both KLAS session tokens (direct login) and long-lived OAuth access tokens (connector flow); OAuth tokens trigger silent KLAS re-login when the 1h session expires
- `main.py` — OAuth router mounted at root (no prefix)

**User flow:** User adds the MCP server URL to Claude → OAuth redirect → enters KLAS credentials once on the hosted login page → credentials stored AES-256 encrypted → Claude gets a long-lived token and never needs credentials again; KLAS sessions auto-refresh silently.

**Required env var:** Set `OAUTH_ENCRYPTION_KEY` (or `SESSION_ENCRYPTION_KEY`) to a Fernet key. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### fix: run alembic migration to resize RAG embedding column 384→1024

Ran `alembic upgrade head` to apply migration `a3e7c2b9f1d5` which resizes `document_chunks.embedding` from 384 to 1024 dimensions for Voyage AI embeddings. POST `/api/rag/ingest` was returning 500 due to the column/model mismatch.

### fix(session): RedisSessionStore.get() now returns created_at; session/info endpoint defensive fallback

`RedisSessionStore.get()` was missing `created_at` in its return dict, causing `GET /api/timetable/session/info` to throw `KeyError` → 500. Fixed in two places: the store now stores and returns `created_at`, and the endpoint falls back to computing it from `expires_at - SESSION_EXPIRE_HOURS` for sessions created before this fix. **Requires server restart to take effect.**

### docs: add comprehensive API reference for frontend clients

Created `docs/API.md` — a full REST API reference covering all 40+ endpoints across authentication, profile, timetable, homework, lecture materials, recorded lectures, RAG, and workflow. Documents request/response schemas, query parameters, auth requirements, error codes, and the two-token system (KLAS session token vs JWT access token).


### feat(autocomplete): golden lecKey swap — automatic OTP bypass for future lectures

`_autocomplete_single` now accepts an optional `golden_key` parameter. When the KLAS viewer blocks a lecture with an OTP wall (`인증에 실패` in the response), it falls back to a pre-acquired lecKey from any already-completed lecture instead of raising an error.

`_run` acquires this key upfront via the new `_get_golden_lec_key()` helper before processing the queue. The helper scans the current subject first, then all timetable subjects, and returns the first lecKey it can extract from a completed (prog=100) lecture's viewer.

**Why this works:** `UpdateProgress.do` does not bind a lecKey to a specific OID — any structurally valid key from the same session is accepted. Completed lectures skip the viewer's OTP check, so their lecKeys are freely obtainable and reusable against uncompleted lectures on OTP-gated weeks.

**Effect:** Autocomplete now works on future lectures regardless of whether the OTP cert check has been completed for that week.

**Files changed:**
- `app/services/progress_service.py` — added `_get_golden_lec_key()`, updated `_autocomplete_single` signature and fallback logic, updated `_run` to pass golden key to each lecture

---

### feat(security): OTP bypass PoC endpoint for bug-bounty

Added `POST /api/recorded-lectures/certi/bypass` — a proof-of-concept endpoint demonstrating that KLAS's lecture certification OTP gate is client-side enforced only.

**How it works:**
1. Calls `CertiLctreStdCheck.do` with a real authenticated KLAS session
2. Records the actual `status` field (which is `false` when OTP is required)
3. Overrides it to `true` in the response (the manipulation)
4. With `probe_viewer=true` (default), also calls `LctreCntntsViewSpvPage.do` directly to test whether KLAS enforces the cert check server-side on subsequent APIs

**Response fields:**
- `real_status` — what KLAS actually returned
- `forced_status` — always `true` (the bypassed value)
- `viewer_leckey_obtained` — `true` if viewer issued a lecKey without OTP → full end-to-end bypass confirmed
- `viewer_auth_error` — `true` if KLAS rejected at the viewer level (server-side enforcement exists)
- `viewer_snippet` — first 400 chars of viewer HTML for evidence

**Files changed:**
- `app/schemas/recorded_lecture.py` — added `CertiBypassResponse`
- `app/api/routes/recorded_lectures.py` — added `/certi/bypass` endpoint

---

### feat: workflow summary endpoint

Added `GET /api/workflow/summary` — a single aggregated endpoint that gives a student a full picture of their academic day without making multiple API calls.

**New files:**
- `app/schemas/workflow.py` — `TodayCourse`, `PendingHomework`, `RecentSummary`, `WorkflowSummary` Pydantic models
- `app/api/routes/workflow.py` — route handler; aggregates timetable, homework, summarize status, and RAG doc count

**Modified files:**
- `main.py` — mounted `/api/workflow` router; added `workflow` to root endpoint map

**What it returns:**
| Field | Source | Description |
|---|---|---|
| `today_courses` | KLAS timetable | Classes scheduled for today, sorted by start time |
| `pending_homework` | KLAS homework | Unsubmitted assignments across all subjects, sorted by deadline |
| `recent_summary` | In-memory summarize status | Latest recorded-lecture summarization job state |
| `rag_document_count` | PostgreSQL | Number of PDFs the student has ingested into RAG |

**Auth:** KLAS session token (Bearer). Uses `student_id` from the session to look up the DB user for the RAG count, so no second token is needed.

---

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
