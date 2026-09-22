<p align="center"><img src="figs/title.png" alt="PaperForge"></p>
<h1 align="center">PaperForge</h1>
<p align="center"><strong>Find it. Fetch it. Organize it.</strong></p>

PaperForge is an agent-native literature workflow for Codex, Claude Code, OpenCode, DSH, and similar coding agents. It turns natural-language research requests, DOI lists, or BibTeX/RIS/EndNote references into traceable PDFs, metadata tables, and failure reports.

## What it does

![PaperForge capabilities](figs/capabilities.png)

PaperForge connects discovery, citation verification, deduplication, authorized acquisition, supplementary-material handling, provenance, and structured delivery in one auditable workflow.

## Inputs and outputs

Inputs include natural-language search requests, DOI/PMID/arXiv lists, BibTeX/RIS/EndNote files, and full-text or supplementary-material requirements.

```text
workspace/pdfs/<doi>.pdf
workspace/metadata.csv / metadata.xlsx / metadata.md
workspace/logs/run-<timestamp>.jsonl / .md
workspace/failures.md
workspace/doi_index.json
```

## Give this to an Agent

```text
Read PaperForge's README.md and SKILL.md first.
Run the environment check and produce a configuration plan.
Do not change configuration yet. Wait for my approval before apply.
Ask me to provide API keys, institutional login, cookies, or browser access myself.
```

## Quick start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1
python 0路由\scripts\envcheck.py
python 0路由\scripts\bootstrap.py check
```

After the check, run `bootstrap.py plan`, show the plan, and only run `bootstrap.py apply` after confirmation.

## Examples

```text
Find 20 highly cited papers on perovskite stability since 2020. Show candidates first; do not download yet.
```

```text
Download this DOI list and produce metadata.csv with title, authors, journal, year, DOI, filename, source, and failure reason.
```

```text
Download the papers in references.bib, preferring open access and institutional access, and record the source used for each item.
```

## Directory structure

![PaperForge directory structure](figs/structure.png)

| Directory | Purpose |
|---|---|
| `0路由/` | Routing, queues, orchestration, environment checks, and output contracts |
| `1学术查询/` | Multi-source search, citation verification, deduplication, and format conversion |
| `2工程化下载/` | Authorized sources, institutional routes, and supplementary materials |
| `docs/` | Design and validation notes |
| `SKILL.md` | Main instructions for the Agent |

## PaperForge workflow

![PaperForge workflow](figs/workflow.png)

Discovery can combine OpenAlex, Crossref, PubMed/PMC, Europe PMC, arXiv, bioRxiv/medRxiv, and optional Semantic Scholar. Acquisition prioritizes Unpaywall/OpenAlex OA, CORE, DOAJ, OpenAIRE, publisher pages or ScienceDirect/Elsevier APIs, institutional WebVPN/EZproxy, and user-authorized browser sessions. `0路由` handles checks, plans, queues, and output contracts; `1学术查询` handles search and normalization; `2工程化下载` handles authorized downloads, supplements, retries, and provenance.

## Compliance and privacy

PaperForge does not grant access to copyrighted content. Users are responsible for complying with local law, institutional subscriptions, publisher terms, and copyright rules. Secrets and runtime outputs remain in the local runtime or user-selected secure configuration.

## License and provenance

Original routing and deployment code is Apache-2.0. Localized upstream components and their changes are documented in [`NOTICE`](NOTICE) and [`PROVENANCE.json`](PROVENANCE.json).
