<div align="center">

<img src="assets/logo.png" width="160" />

# OpenKLAS MCP

An open-source FastAPI backend that wraps [KLAS](https://klas.kw.ac.kr) — Kwangwoon University's Learning Management System — and exposes it as a clean REST API with built-in MCP support for AI assistants.

> Developed by [@univerxe](https://github.com/univerxe) · Open to contributions

See what OpenKLAS does and how to set it up at [openklas.com](https://openklas.com). To plug it into Claude.ai (or any MCP-compatible assistant) right now, add a custom connector with the URL `https://mcp.openklas.com/mcp` — you'll sign into KLAS once on the OpenKLAS login page and the full tool catalog becomes available.

---

## Tech Stack

<p>
  <img src="https://skillicons.dev/icons?i=python,fastapi,postgres,redis,docker" />
</p>
<p>
  <img src="https://img.shields.io/badge/Claude-Anthropic-D97757?style=for-the-badge&logo=anthropic&logoColor=white" />
  <img src="https://img.shields.io/badge/Groq-Whisper-F55036?style=for-the-badge&logo=groq&logoColor=white" />
  <img src="https://img.shields.io/badge/Voyage_AI-Embeddings-6C47FF?style=for-the-badge&logoColor=white" />
  <img src="https://img.shields.io/badge/Ollama-RAG-000000?style=for-the-badge&logo=ollama&logoColor=white" />
  <img src="https://img.shields.io/badge/pgvector-Vector_Search-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" />
</p>

</div>

---

## Major Features

- **MCP Server** — every endpoint is a Claude tool via `fastapi-mcp`; connect to Claude.ai as a custom OAuth connector
- **KLAS Auth** — RSA-encrypted login, dual-token system (session token + JWT)
- **Homework & Lectures** — proxies assignments, lecture boards, course syllabi, team projects
- **Recorded Lecture Pipeline** — download → Whisper transcribe → Claude summarize → save to Obsidian
- **RAG** — ingest lecture PDFs, query them with Voyage AI embeddings + pgvector + Ollama
- **Autocomplete** — automated lecture progress completion

---

## Using Claude as a KLAS Agent

Connect OpenKLAS to Claude.ai once and ask anything about your courses in plain English. Claude uses the MCP tools to look up live data from KLAS and responds in seconds.

### Remaining Lectures
One question. Every course. Aggregate progress. Claude scans every recorded-lecture board for you and reports back exactly which weeks remain in which subjects, with durations and deadlines included.

![Remaining lectures](https://openklas.com/projects/10_project/feature_lectures.png)

### Homework Overview
Every deadline, ranked by what actually matters. Ask once. Get pending, overdue, and submitted assignments across every subject in a single response, sorted by deadline, with overdue items flagged.

![Homework overview](https://openklas.com/projects/10_project/feature_homework.png)

### Assignment Detail
Format, deadline, content checklist, all in one prompt. Stop opening four KLAS tabs to figure out what an assignment wants. Claude pulls the full task detail and surfaces it as a clean checklist.

![Assignment detail](https://openklas.com/projects/10_project/feature_assignment.png)

### Email Drafting
One English sentence in. A polite Korean email out. Need to ask for a late-submission extension? Claude looks up the assignment, finds the right professor, and drafts a respectful Korean email ready to send.

![Email drafting](https://openklas.com/projects/10_project/feature_email.png)

### PDF Q&A
Talk to your lecture PDFs like they're a tutor. Upload your slides once. Ask anything later. Voyage AI embeddings + pgvector + Ollama keep the answers grounded, per-user, isolated by design.

![PDF Q&A](https://openklas.com/projects/10_project/feature_pdf_qa.png)

### Lecture Summarization
From an hour-long video to study-ready notes. Download → Whisper transcription → Claude-written summary, optionally saved straight to your Obsidian vault. Walk into class already prepped.

![Lecture summarization](https://openklas.com/projects/10_project/feature_summarize.png)

---

## Architecture

### System Overview

```mermaid
graph TD
    subgraph Clients
        A[Claude.ai / Claude Desktop]
        B[Browser / REST client]
    end

    subgraph OpenKLAS["OpenKLAS Backend (FastAPI)"]
        MCP[MCP Server\nSSE /mcp]
        OAuth[OAuth 2.0\n/oauth/*]
        API[REST API\n/api/*]
        BG[Background Tasks\nsummarize · autocomplete]
    end

    subgraph Session["Session Layer"]
        Redis[(Redis\nsession store)]
        PG[(PostgreSQL\n+ pgvector)]
    end

    subgraph External["External Services"]
        KLAS[klas.kw.ac.kr\nKLAS LMS]
        KWC[kwcommons.kw.ac.kr\nvideo CDN]
        Groq[Groq\nWhisper API]
        Anthropic[Anthropic\nClaude API]
        Voyage[Voyage AI\nEmbeddings]
    end

    subgraph Infra["Infrastructure"]
        Caddy[Caddy\nreverse proxy / TLS]
    end

    A -->|OAuth Bearer / SSE| Caddy
    B -->|HTTPS| Caddy
    Caddy --> MCP
    Caddy --> OAuth
    Caddy --> API

    MCP --> API
    OAuth --> PG
    API --> BG

    API -->|RSA-encrypted login\nscrape data| KLAS
    BG -->|Playwright + httpx\nvideo download| KWC
    BG -->|audio file| Groq
    BG -->|transcript| Anthropic
    API -->|PDF chunks| Voyage
    API -->|question| Anthropic

    API --> Redis
    API --> PG
```

### OAuth + MCP Login Flow

```mermaid
sequenceDiagram
    actor User
    participant Claude as Claude.ai
    participant API as OpenKLAS API
    participant KLAS as klas.kw.ac.kr
    participant DB as PostgreSQL
    participant Redis as Redis

    User->>Claude: Add MCP connector\n(mcp.openklas.com/mcp)
    Claude->>API: GET /.well-known/oauth-authorization-server
    API-->>Claude: OAuth metadata (endpoints, scopes)
    Claude->>API: POST /oauth/register
    API-->>Claude: client_id / client_secret
    Claude->>User: Redirect to /oauth/authorize
    User->>API: POST credentials (student_id + password)
    API->>KLAS: RSA-encrypted login
    KLAS-->>API: Session cookie
    API->>Redis: Store KLAS session
    API->>DB: Upsert OAuthToken (encrypted credentials)
    API-->>Claude: auth code → redirect
    Claude->>API: POST /oauth/token (exchange code)
    API-->>Claude: long-lived access_token
    Claude->>API: MCP tool calls (Bearer access_token)
    Note over API,Redis: On token expiry: silent re-login\nusing stored encrypted credentials
```

### Recorded Lecture Summarization Pipeline

```mermaid
flowchart TD
    A([POST /api/recorded-lectures/summarize]) --> B[Validate — no job running\ncheck semaphore]
    B --> C[Return 202 Accepted\nbackground job started]
    C --> D[Acquire semaphore\nmax 1 pipeline at a time]
    D --> E[Playwright: browser login\nklas.kw.ac.kr]
    E --> F[Navigate to player\nkwcommons.kw.ac.kr/em/code]
    F --> G[Extract session cookies]
    G --> H[httpx stream download\n1 MB chunks → tmp .mp4]
    H --> I[ffmpeg: extract audio\n16kHz mono MP3]
    I --> J[Groq Whisper API\nwhisper-large-v3-turbo]
    J --> K[Strip control chars\nfrom transcript]
    K --> L[Claude claude-sonnet-4-6\nstructured summary]
    L --> M{Save to Obsidian?}
    M -->|yes| N[Write .md to vault\ncourse/lectures/WN-title.md]
    M -->|no| O([step=done])
    N --> O

    P([GET /summarize/status]) -.->|poll| Q[SummarizeStatus\nstep · transcript · summary]
    P2([GET /summarize/status/stream]) -.->|SSE push| Q
```

### RAG Pipeline

```mermaid
flowchart TD
    subgraph Ingest
        A([POST /api/rag/ingest\nPDF upload]) --> B[Extract text\npage by page]
        B --> C[Semantic chunking]
        C --> D[Voyage AI\nvoyage-3 embeddings\n1024-dim]
        D --> E[(pgvector\nDocumentChunks)]
    end

    subgraph Query
        F([POST /api/rag/query\nquestion]) --> G[Voyage AI\nembed question]
        G --> H[pgvector cosine\nnearest-neighbor search]
        E --> H
        H --> I[Top-k chunks\nas context]
        I --> J[Claude\ngrounded answer]
        J --> K([response])
    end

    Ingest --> Query
```

---

## Contributing

Contributions are welcome! Feel free to open issues or pull requests.

1. Fork the repo
2. Create a branch (`git checkout -b feat/your-feature`)
3. Commit and push
4. Open a pull request
