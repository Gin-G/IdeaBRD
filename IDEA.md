---
status: active
progress: 88
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
front end, deployed to Kubernetes by Argo CD with secrets from OpenBao, plus an
Android app that reads the board straight from git. Backend lives in
`backend/app`, the UI in `frontend/src`, the chart in `chart/`, the app in
`android/`; `docker-compose.yml` runs the stack locally and `backend/tests`
holds the pytest suite. Every board change is now dual-written to a git repo,
and the phone reads that repo with no server at all — the database stays
authoritative until reconciliation says the git copy has earned the swap.

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
- [x] Show richer issue data on the tile (labels, assignee, comment count), and import a repo's existing issues as to-dos instead of only pushing new ones
- [x] Add `/api/webhooks/github` so an issue closed on GitHub pushes to the tile over the existing WebSocket, instead of the change waiting for someone to open the tile
- [x] Page the issue pull past the first 100, or retire it once webhooks land — a to-do pointing at an older issue currently keeps whatever state it already had
- [x] Mount the to-do list in `IdeaModal.svelte` too; the promote action only exists on the full idea page
- [x] Decide on GitHub Projects v2 — decided against, and the reasons are in `docs/github-projects-v2.md` so they don't get rediscovered: GraphQL-only, needs a scope every existing login would have to re-authorize for, and projects are user-owned so an idea would need its own project id plus a Status field mapping
- [x] Back up the Postgres cluster — it runs a single CNPG instance with no replica
- [x] Define the board repo layout — one directory per idea and no manifest, with order and colour in each idea's own frontmatter, so moving a tile rewrites one file instead of a file every board shares
- [x] Give every idea a stable id that outlives Postgres and backfill it, since a serial primary key can't be the identity a git-only board is keyed by
- [x] Publish the whole board to the central repo, so a complete git copy exists before anything is asked to depend on it
- [x] Dual-write every idea mutation to the board repo, leaving the database authoritative while the git copy earns trust
- [x] Reconcile the board repo against the database and report the diff, so cutover is a decision backed by evidence rather than a leap
- [x] Port `ideafile.py` to Kotlin with its tests — the load-bearing spike, since the phone owns parsing once no server does
- [x] Merge IDEA.md semantically rather than by line: parse both sides, match to-dos the way `_apply_todos` already does, re-render
- [x] Ship the existing SvelteKit SPA as an Android app via Capacitor, with a native plugin for JGit and Keystore-backed tokens
- [x] Authenticate on device with the GitHub device flow, since an app distributed to users can't ship a client secret
- [x] Release the Android app from a GitHub Actions workflow on a version tag, signed and attached to a release
- [x] Hold both IDEA.md renderers to the same golden files, so the Kotlin port and the Python one can't drift into writing different bytes for the same idea
- [ ] Cut over to git as the only store and retire the database, chart and cluster once the board repo has proven itself
- [x] Name a shared idea on a collaborator's board — slugs are unique per owner, so an idea shared onto a board that already has that directory has nowhere to go
- [x] Refuse to publish over a board repo that moved since last time — `board_commit_sha` is recorded on every publish and read by nothing, so a direct edit to the repo is silently overwritten
- [ ] Let collaboration be git's: two people who both link an idea's repo collaborate there by branch and PR, so IdeaCollaborator, IdeaInvitation and roles retire at cutover in favour of repo permissions
- [x] Promote a note-only idea to its own repo — an idea kept inside a board repo has nowhere for anyone else to link, so giving it a repo is what sharing now means
- [x] Stop the board repo copying a linked idea at all — it records a reference and the board keys, so there is no second copy of the notes, to-dos or logo to explain, and none that can drift
- [x] Show open pull requests on a repo-linked tile, now that a PR is where an idea's collaboration actually happens
- [x] Create a board repo from the app on first run — pick the account or org, get an empty repo, and publish the existing board into it as that repo's first commit
- [ ] Run the live GitHub suite against a real repo — `backend/tests/live` and a weekly workflow now exist, but nothing has actually run them until `IDEABRD_GITHUB_TOKEN` is set on the repository
- [ ] Try the Android app on real hardware — v0.1.0 is released and installable from GitHub, but JGit on a device (clone size, storage, background time limits) has never been exercised
- [ ] Give the Android release a stable signing key — `android/scripts/make-signing-key.sh` makes one and prints the four secrets to set; until they exist every release is signed differently and Android refuses to install one over another
- [ ] Point a GitHub webhook at the deployment and put `webhook_secret` in OpenBao — the receiver refuses every request until the secret exists, so it is code that isn't running yet
- [x] Read a repo-linked idea on the phone — the board repo records only where such an idea lives, so a linked tile was a link and an empty page; the app now clones that repository on request and reads and writes its own IDEA.md
- [x] Show issue-backed to-dos properly on the phone — issues are fetched and cached for offline, the item they back takes its title and state from them, and ticking a box closes the issue
- [x] Do the GitHub-side actions from the phone — promoting a to-do to an issue, importing a repo's open issues, and giving a held idea a repository of its own, which is created, pushed to, and left as a reference on the board
- [x] Link an idea to an existing repo from the phone, with the same opt-in the server asks for — a repo that already has an IDEA.md is adopted, and one that hasn't is left untouched until a second, explicit yes
