---
status: active
progress: 95
---

# IdeaBRD

A personal idea board: each idea is a tile with notes, a to-do list, progress
tracking and live GitHub data for repo-linked projects. FastAPI + async
SQLAlchemy on Postgres (CNPG), SvelteKit + Tailwind front end, deployed to
Kubernetes by Argo CD with secrets from OpenBao. Backend lives in `backend/app`,
the UI in `frontend/src`, the chart in `chart/`; `docker-compose.yml` runs the
whole stack locally and `backend/tests` holds the pytest suite.

## Editing this file

This file is the source of truth for the idea's details. IdeaBRD re-reads it
every time the idea is opened and overwrites its own copy, so an edit here
appears on the board within a page load — and edits made in the app are
committed back here. Keep the shape below, because the parser
(`backend/app/ideafile.py`) silently discards anything it cannot read:

- `status:` must be one of `idea`, `active`, `paused`, `done`; `progress:` is an
  integer 0-100. Other frontmatter keys are ignored.
- The `# ` heading is the idea title. Prose under it becomes the notes shown on
  the board — including this section, so keep it brief.
- To-dos go under a `## Todos` heading as `- [ ]` / `- [x]` lines. Non-item
  lines in that section are dropped, and a later `## ` heading ends the list.

Items are matched back to existing rows by their exact text, so rewording a
to-do replaces it rather than editing it in place.

## Todos

- [x] Google OIDC login with signed session cookies
- [x] GitHub OAuth login and multi-provider account linking
- [x] Per-user GitHub token for repo access, replacing the shared PAT
- [x] Idea-level collaboration with live sync
- [x] Two-way git sync of idea details through IDEA.md
- [x] Fix pulls leaving stale to-dos behind — the delete was never awaited, so items removed or reworded in the file came back as duplicates
- [x] Move the to-do list below Notes and wrap long items, instead of squeezing it into the 20rem side column where it overflowed
- [x] Helm chart deployed by Argo CD, secrets via ExternalSecrets/OpenBao
- [x] Normalize `github_repo` to `owner/name` on write, so repo links stop doubling up, and backfill the rows that stored a full clone URL
- [x] Drag-and-drop tile reordering on the board, with Alt+arrow as the keyboard equivalent
- [x] Image upload for tile logos, stored in Postgres and served from `/api/ideas/{id}/logo`
