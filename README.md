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

## Contributing

Contributions are welcome! Feel free to open issues or pull requests.

1. Fork the repo
2. Create a branch (`git checkout -b feat/your-feature`)
3. Commit and push
4. Open a pull request
