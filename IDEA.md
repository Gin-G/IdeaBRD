---
status: active
progress: 95
---

# IdeaBRD

<!--
IdeaBRD parses this file. It is the source of truth for this idea's tile:
the app re-reads it on every open and commits its own edits back here, so
the shape below matters more than it looks. Anything the parser
(backend/app/ideafile.py) can't read is dropped silently.

  frontmatter  status: one of idea, active, paused, done. progress: 0-100.
               Any other key is ignored.
  # heading    The idea title (first H1).
  prose        Everything outside the Todos section becomes the tile's
               notes, shown on the board — so keep it short. Documentation
               written here is published, not filed away.
  ## Todos     That heading exactly (or "## To-Dos"); "## ToDo", "## TODO"
               and "## Tasks" do not match and the whole list is lost.
               Inside it, only "- [ ] open" / "- [x] done" lines survive:
               sub-headings and blank-line grouping are discarded, and a
               wrapped item is cut at the line break, so keep each to-do on
               one line. The next "## " heading ends the list.

To-dos are matched to the board by exact text, so rewording one replaces it
rather than editing it in place — expect a checked item to come back
unchecked if you reword it.

HTML comments are stripped on read, so this block never reaches the board.
-->

A personal idea board: each idea is a tile with notes, a to-do list, progress
tracking and live GitHub data for repo-linked projects. FastAPI + async
SQLAlchemy on Postgres (CNPG), SvelteKit + Tailwind front end, deployed to
Kubernetes by Argo CD with secrets from OpenBao. Backend lives in `backend/app`,
the UI in `frontend/src`, the chart in `chart/`; `docker-compose.yml` runs the
whole stack locally and `backend/tests` holds the pytest suite.

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
- [x] Track the tile logo in git as `idea_logo.<ext>` beside IDEA.md, so a linked repo carries its own artwork and any board that links it builds the tile from the repo
- [x] Write the IDEA.md format rules into every file as a stripped-on-read HTML comment, with the `## Todos` heading always present — a seeded stub was the whole spec its next editor saw, and the rules only existed in this repo
