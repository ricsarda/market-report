# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## WAT Framework Architecture

This project uses the **WAT (Workflows, Agents, Tools)** pattern — AI handles orchestration, Python scripts handle execution.

- **`workflows/`** — Markdown SOPs defining objective, inputs, tools, outputs, and edge case handling
- **`tools/`** — Python scripts for deterministic execution (API calls, data transforms, file ops). Credentials via `.env`
- **`.tmp/`** — Disposable intermediate files, regenerated as needed
- **Deliverables** — Final outputs go to cloud services (Google Sheets, Slides, etc.), not local files
- **`credentials.json`, `token.json`** — Google OAuth (gitignored)

## Operating Rules

**Before building anything**: check `tools/` for an existing script that matches the task. Only create new scripts when nothing exists.

**When hitting errors**:
1. Read the full trace
2. Fix the script and retest (check before re-running if it uses paid API calls)
3. Update the workflow with what you learned (rate limits, timing quirks, batch endpoints, etc.)

**Workflows are persistent instructions**: do not create or overwrite workflow files without explicit permission. Update them when you find better methods or encounter constraints.

**Why deterministic tools matter**: chaining 5 steps at 90% accuracy yields ~59% end-to-end success. Offloading execution to tested scripts keeps failure rates low.

## Self-Improvement Loop

When something breaks: fix the tool → verify → update the workflow → continue. This is how the system improves over time.
