---
status: active
progress: 75
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
  (#12)        A to-do ending in an issue reference is backed by that issue
               in this repo. The issue wins: its title becomes the to-do's
               text and its open/closed state the checkbox, both here and on
               the board. Ticking the box in the app closes the issue.

Working in this repo? This file is the to-do list — use it rather than
starting a parallel one. Tick items off as you finish them, add new ones as
you find them, and keep status/progress honest: a TODO.md, a plan in a chat
window or a checklist in a commit message is invisible to everyone reading
the board. For work worth assigning, discussing, or writing up at length,
open a real issue and append its "(#12)" to the line — the item is then
tracked by number instead of text, and the issue holds the detail this file
has no room for (prose here is published to the board, not filed away).

To-dos without an issue are matched to the board by exact text, so rewording
one replaces it rather than editing it in place — expect a checked item to
come back unchecked if you reword it. Issue-backed to-dos are matched by
number instead, so keep the "(#12)" and reword freely; drop the reference and
the item becomes an ordinary to-do again (the issue itself is left alone).

HTML comments are stripped on read, so this block never reaches the board.
-->

A personal idea board: each idea is a tile with notes, a to-do list that can be
backed by GitHub issues, progress tracking and live GitHub data for repo-linked
projects. FastAPI + async SQLAlchemy on Postgres (CNPG), SvelteKit + Tailwind
front end, deployed to Kubernetes by Argo CD with secrets from OpenBao. Backend
lives in `backend/app`, the UI in `frontend/src`, the chart in `chart/`;
`docker-compose.yml` runs the whole stack locally and `backend/tests` holds the
pytest suite. Moving to a git-only model next: a central board repo becomes the
source of truth so an Android app can run standalone, with the database
dual-written and kept authoritative until the repo has proven itself.

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
- [x] Back to-dos with GitHub issues: promote one from the tile, mirror its title and open/closed state in both directions, and carry the reference as `(#12)` in this file — issue-backed items are matched by number instead of text, so rewording one stops silently replacing it
- [x] Tell whoever edits IDEA.md next that it *is* the tracker — the format rules said how to write the file but never that progress and new work belong in it rather than a side channel
- [ ] Show richer issue data on the tile (labels, assignee, comment count), and import a repo's existing issues as to-dos instead of only pushing new ones
- [ ] Add `/api/webhooks/github` so an issue closed on GitHub pushes to the tile over the existing WebSocket, instead of the change waiting for someone to open the tile
- [ ] Page the issue pull past the first 100, or retire it once webhooks land — a to-do pointing at an older issue currently keeps whatever state it already had
- [ ] Mount the to-do list in `IdeaModal.svelte` too; the promote action only exists on the full idea page
- [ ] Decide on GitHub Projects v2 — GraphQL-only so none of `app/github.py` is reusable, needs the `project` scope added (every existing GitHub identity has to re-authorize, since OAuth tokens don't gain scopes), and projects are user/org-owned so an idea needs its own project id plus a per-project Status field option mapping
- [ ] Back up the Postgres cluster — it runs a single CNPG instance with no replica
- [x] Define the board repo layout — one directory per idea and no manifest, with order and colour in each idea's own frontmatter, so moving a tile rewrites one file instead of a file every board shares
- [x] Give every idea a stable id that outlives Postgres and backfill it, since a serial primary key can't be the identity a git-only board is keyed by
- [x] Publish the whole board to the central repo, so a complete git copy exists before anything is asked to depend on it
- [ ] Dual-write every idea mutation to the board repo, leaving the database authoritative while the git copy earns trust
- [ ] Reconcile the board repo against the database and report the diff, so cutover is a decision backed by evidence rather than a leap
- [ ] Port `ideafile.py` to Kotlin with its tests — the load-bearing spike, since the phone owns parsing once no server does
- [ ] Merge IDEA.md semantically rather than by line: parse both sides, match to-dos the way `_apply_todos` already does, re-render
- [ ] Ship the existing SvelteKit SPA as an Android app via Capacitor, with a native plugin for JGit and Keystore-backed tokens
- [ ] Authenticate on device with the GitHub device flow, since an app distributed to users can't ship a client secret
- [ ] Cut over to git as the only store and retire the database, chart and cluster once the board repo has proven itself
- [x] Name a shared idea on a collaborator's board — slugs are unique per owner, so an idea shared onto a board that already has that directory has nowhere to go
- [ ] Refuse to publish over a board repo that moved since last time — `board_commit_sha` is recorded on every publish and read by nothing, so a direct edit to the repo is silently overwritten
- [ ] Let collaboration be git's: two people who both link an idea's repo collaborate there by branch and PR, so IdeaCollaborator, IdeaInvitation and roles retire at cutover in favour of repo permissions
- [ ] Promote a note-only idea to its own repo — an idea kept inside a board repo has nowhere for anyone else to link, so giving it a repo is what sharing now means
- [ ] Say in a board repo's copy of a linked idea that it is a cache and the linked repo wins, the same way every IDEA.md already carries its own format rules
- [ ] Show open pull requests on a repo-linked tile, now that a PR is where an idea's collaboration actually happens
- [x] Create a board repo from the app on first run — pick the account or org, get an empty repo, and publish the existing board into it as that repo's first commit
- [ ] Check the GitHub client against a real repo, not just respx — the publisher's tests all passed while GitHub refused every git data write to a repo with no commits
