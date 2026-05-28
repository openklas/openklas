# OpenKLAS API

An open-source FastAPI backend that wraps [KLAS](https://klas.kw.ac.kr) — Kwangwoon University's Learning Management System — and exposes it as a clean REST API with built-in MCP support for AI assistants.

> Developed by [@univerxe](https://github.com/univerxe) · Open to contributions

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

## Major Features

- **MCP Server** — every endpoint is a Claude tool via `fastapi-mcp`; connect to Claude.ai as a custom OAuth connector
- **KLAS Auth** — RSA-encrypted login, dual-token system (session token + JWT)
- **Homework & Lectures** — proxies assignments, lecture boards, course syllabi, team projects
- **Recorded Lecture Pipeline** — download → Whisper transcribe → Claude summarize → save to Obsidian
- **RAG** — ingest lecture PDFs, query them with Voyage AI embeddings + pgvector + Ollama
- **Autocomplete** — automated lecture progress completion

## Quick Start

```bash
cp .env.example .env   # fill in KLAS URLs, DB, API keys
docker compose up
```

API: `http://localhost:8000` · Docs: `http://localhost:8000/docs`

## Contributing

Contributions are welcome! Feel free to open issues or pull requests for bug fixes, new features, or improvements.

1. Fork the repo
2. Create a branch (`git checkout -b feat/your-feature`)
3. Commit and push
4. Open a pull request
