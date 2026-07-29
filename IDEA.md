---
status: active
progress: 70
---

# IdeaBRD

A personal idea board. Each idea is a tile with notes, a to-do list, progress
tracking and live GitHub data for repo-linked projects. Ideas linked to a repo
keep their details in `IDEA.md`, synced two ways — git is the source of truth.

Stack: FastAPI + SQLAlchemy (async) on Postgres via CNPG, SvelteKit + Tailwind
front end, deployed to Kubernetes by Argo CD with secrets from OpenBao.

## Todos

- [x] Google OIDC login with signed session cookies
- [x] GitHub OAuth login and multi-provider account linking
- [x] Per-user GitHub token for repo access (replaces the shared PAT)
- [x] Idea-level collaboration with live sync
- [x] Two-way git sync of idea details through IDEA.md
- [x] Helm chart deployed by Argo CD, secrets via ExternalSecrets/OpenBao
- [ ] Fix broken GitHub links: github_repo is stored as a full clone URL, so the UI builds https://github.com/https://github.com/owner/name.git — normalize to owner/name on write and backfill existing rows
- [ ] Drag-and-drop tile reordering (reorder API and positions already exist)
- [ ] Image upload for tile logos (currently an emoji or an image URL)
- [ ] Add a backup target for the CNPG cluster — it now runs a single instance with no replica
