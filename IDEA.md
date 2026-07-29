---
status: active
progress: 70
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
- [x] Helm chart deployed by Argo CD, secrets via ExternalSecrets/OpenBao
- [ ] Fix repo links: `github_repo` is saved as typed, so full clone URLs get interpolated into hrefs and double up. Normalize to `owner/name` on write in `routers/ideas.py` and backfill existing rows; `github.normalize_repo` already does the parsing
- [ ] Wrap long to-do text: the `flex-1` span in `TodoList.svelte` keeps `min-width: auto`, so long words overflow the card instead of wrapping. Add `min-w-0` + `break-words`, and `shrink-0` on the delete button
- [ ] Drag-and-drop tile reordering — `PATCH /api/ideas/reorder` and the position columns already exist, so this is front-end only
- [ ] Image upload for tile logos, which today accept only an emoji or an image URL
- [ ] Give the CNPG cluster a backup target — it runs a single instance with no replica
