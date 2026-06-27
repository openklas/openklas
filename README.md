<div align="center">

<img src="assets/logo.png" width="160" />

# OpenKLAS MCP

An open-source FastAPI backend that wraps [KLAS](https://klas.kw.ac.kr) — Kwangwoon University's Learning Management System — and exposes it as a clean REST API with built-in MCP support for AI assistants.

> Developed by [@univerxe](https://github.com/univerxe) · Open to contributions

See what OpenKLAS does and how to set it up at [openklas.com](https://openklas.com). To plug it into Claude.ai (or any MCP-compatible assistant) right now, add a custom connector with the URL `https://mcp.openklas.com/mcp` — you'll sign into KLAS once on the OpenKLAS login page and the full tool catalog becomes available.

---

## Screenshots

<table>
  <tr>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_lectures.png" alt="Lectures left to watch" />
      <br/>
      <sub><b>Remaining lectures</b> — One question. Every course. Aggregate progress. Claude scans every recorded-lecture board for you and reports back exactly which weeks remain in which subjects, with durations and deadlines included.</sub>
    </td>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_homework.png" alt="Homework status across all subjects" />
      <br/>
      <sub><b>Homework overview</b> — Every deadline, ranked by what actually matters. Ask once. Get pending, overdue, and submitted assignments across every subject in a single response, sorted by deadline, with overdue items flagged.</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_assignment.png" alt="Assignment detail checklist" />
      <br/>
      <sub><b>Assignment detail</b> — Format, deadline, content checklist, all in one prompt. Stop opening four KLAS tabs to figure out what an assignment wants. Claude pulls the full task detail and surfaces it as a clean checklist.</sub>
    </td>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_email.png" alt="Korean email draft for late submission" />
      <br/>
      <sub><b>Email drafting</b> — One English sentence in. A polite Korean email out. Need to ask for a late-submission extension? Claude looks up the assignment, finds the right professor, and drafts a respectful Korean email ready to send.</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_pdf_qa.png" alt="PDF Q&A from lecture slides" />
      <br/>
      <sub><b>PDF Q&amp;A</b> — Talk to your lecture PDFs like they're a tutor. Upload your slides once. Ask anything later. Voyage AI embeddings + pgvector + Ollama keep the answers grounded, per-user, isolated by design.</sub>
    </td>
    <td align="center" width="50%">
      <img src="https://openklas.com/projects/10_project/feature_summarize.png" alt="Video lecture summarization" />
      <br/>
      <sub><b>Lecture summarization</b> — From an hour-long video to study-ready notes. Download → Whisper transcription → Claude-written summary, optionally saved straight to your Obsidian vault. Walk into class already prepped.</sub>
    </td>
  </tr>
</table>

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
