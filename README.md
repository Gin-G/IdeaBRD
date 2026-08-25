# IdeaBRD

A personal **idea board**. Log in with Google, get a grid of tiles — one per idea — and click
into any tile for notes, a to-do list, progress tracking, and live GitHub data for repo-linked
ideas. Share individual ideas with collaborators (editor/viewer) and they sync **live** over a
WebSocket. Built to run on Kubernetes.

```
┌──────────── Browser ────────────┐
│  SvelteKit SPA (static, nginx)  │  ← frontend image
└───────────────┬─────────────────┘
       Ingress  │  /api → backend, / → SPA
┌───────────────┴─────────────────┐
│  FastAPI (uvicorn)  /api/*       │  ← backend image
│   ├── CloudNativePG (Postgres)   │
│   ├── Google OIDC (Authlib)      │
│   └── GitHub REST (httpx, cached)│
└──────────────────────────────────┘
```

- **Frontend** — SvelteKit compiled to a static SPA (`adapter-static`), served by nginx — and
  packaged as an **Android app** (`android/`), where the same pages read the board from a git
  checkout instead of the API.
- **Backend** — FastAPI, async SQLAlchemy + asyncpg, Alembic migrations. Google OIDC handled
  server-side with an httpOnly signed session cookie.
- **Database** — CloudNativePG `Cluster` (in-cluster Postgres).
- **Packaging** — a single Helm chart (`chart/`) with both apps, ingress, secrets, the CNPG
  cluster, and a migration hook Job.

## Repository layout

| Path        | What                                                            |
|-------------|----------------------------------------------------------------|
| `backend/`  | FastAPI app, models, routers, Alembic migrations, tests        |
| `frontend/` | SvelteKit SPA (Tailwind), nginx Dockerfile                     |
| `chart/`    | Helm chart (Deployments, Services, Ingress, Secret, CNPG, Job) |
| `android/`  | The Android app: Capacitor shell, JGit plugin, shared Kotlin core |
| `fixtures/` | Golden `IDEA.md` files both renderers are held to               |
| `docs/`     | Decisions worth writing down                                    |
| `docker-compose.yml` | Local dev stack                                        |

---

## Local development

```bash
cp .env.example .env        # edit as needed (works as-is with a dev login)
docker compose up --build
```

- Frontend: http://localhost:5173 (Vite, proxies `/api` → backend)
- Backend:  http://localhost:8000 (`/api/health`, `/docs`)
- Postgres: localhost:5432

Without Google credentials the backend uses a **dev login**: hitting *Sign in* logs you into a
single shared local user so you can use the whole app immediately. Add `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` to `.env` for real Google sign-in (redirect URI
`http://localhost:8000/api/auth/callback`).

### Run the backend directly

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload            # needs a Postgres in DATABASE_URL
```

### Run the frontend directly

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run check      # type-check
npm run build      # static SPA -> build/
```

---

## Building images

Images are built by **GitHub Actions** (`.github/workflows/{backend,frontend}-build.yaml`): a
push under `backend/` or `frontend/` builds and pushes a datetime-tagged image
(`ncging/ideabrd-*:YYYY-MM-DD.HH.MM`) to Docker Hub, then `sed`-bumps the tag in
`chart/values.yaml` and commits it back — Argo CD then rolls out the new version. Requires repo
secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Trigger the first build manually via
*Actions → Run workflow* (`workflow_dispatch`) to seed real image tags.

To build locally instead:

```bash
docker build -t docker.io/ncging/ideabrd-backend:$(date +%Y-%m-%d.%H.%M) backend
docker build -t docker.io/ncging/ideabrd-frontend:$(date +%Y-%m-%d.%H.%M) frontend
```

---

## Deploying to Kubernetes

The chart (`chart/`) follows the same conventions as the cluster's other apps:
**External Secrets Operator + OpenBao** for all secrets, **CloudNativePG** bootstrapped from
ESO-provided credentials, a single **Traefik** ingress (cert-manager + external-dns) with an
optional security-headers Middleware, and everything driven from `chart/values.yaml`. It is
intended to be deployed by **Argo CD** (see `argocd/ideabrd-application.yaml`).

### Cluster prerequisites

- **CloudNativePG operator** (provides the `Cluster` CRD)
- **External Secrets Operator** (provides `SecretStore` / `ExternalSecret`)
- **Traefik** ingress controller (provides the `Middleware` CRD; `traefik` IngressClass)
- **OpenBao/Vault** reachable at `openbao.openbao.svc.cluster.local:8200`, plus an
  `openbao-credentials` Secret (key `OPENBAO_TOKEN`) in the `ideabrd` namespace
- cert-manager `ClusterIssuer` `letsencrypt-cloudflare` and external-dns (for the ingress)

### OpenBao secret paths

The chart's ExternalSecrets read from these KV paths (override via `values.yaml`):

| Path (`kv/...`) | Properties |
|-----------------|------------|
| `ideabrd/db`      | `dbsu`, `dbsupassw` (superuser), `dbuser`, `dbpassw` (app user) |
| `ideabrd/backend` | `session_secret`, `google_client_id`, `google_client_secret`, `github_token` |
| `ideabrd/github`  | `client_id`, `client_secret` (GitHub OAuth app) |

**GitHub login** needs a GitHub OAuth app (callback
`https://<fqdn>/api/auth/github/callback`) whose `client_id` + `client_secret` live at
`backend.githubSecretPath`, plus `backend.githubOAuth: true` in `values.yaml`. (The flag
gates those two ExternalSecret keys — without the OpenBao values present the sync would fail.)

> The app-user value at `ideabrd/db:dbuser` **must equal** `db.app.owner` in `values.yaml`
> (CNPG creates the owning role from that secret).

### Install

Set your hostname, images, and OpenBao paths in `chart/values.yaml`, then either let Argo sync
it, or install directly:

```bash
helm install ideabrd ./chart --namespace ideabrd --create-namespace
```

What happens:

- A `SecretStore` (`openbao-backend`) and three `ExternalSecret`s materialize the backend
  config Secret plus the CNPG superuser/app-user Secrets from OpenBao.
- A CNPG `Cluster` boots Postgres using those credentials; the backend builds
  `DATABASE_URL` as `postgresql+asyncpg://$(DB_USER):$(DB_PASS)@ideabrd-db-rw:5432/ideabrd`.
- A post-install **migrate Job** runs `alembic upgrade head`.
- One Traefik Ingress on `frontend.fqdn` routes `/api` → backend and `/` → SPA (TLS via
  cert-manager), with a security-headers Middleware attached.

Set the Google OAuth **redirect URI** to `https://<frontend.fqdn>/api/auth/callback`.

### Key values

| Value | Default | Notes |
|-------|---------|-------|
| `frontend.fqdn` | `ideabrd.nickknows.net` | Public hostname (ingress host + OAuth redirect) |
| `ingress.className` | `traefik` | Ingress class |
| `ingress.securityHeaders` | `true` | Attach the Traefik security-headers Middleware |
| `frontend.container.image` / `backend.container.image` | `docker.io/ncging/ideabrd-*:latest` | Images to deploy |
| `backend.cookieSecure` | `true` | Secure session cookie (HTTPS) |
| `backend.secretPath` / `db.secretPath` | `ideabrd/backend`, `ideabrd/db` | OpenBao KV paths |
| `db.instances` / `db.size` | `3`, `10Gi` | CNPG replicas and volume size |
| `db.app.name` / `db.app.owner` | `ideabrd` | Database name / owning role |

### GitOps with Argo CD

`argocd/ideabrd-application.yaml` is an app-of-apps template mirroring the `rts` Application
(gated by `index .Values "ideabrd" "enable"`, `path: chart/`). Add an `ideabrd` block to your
app-of-apps `values.yaml`:

```yaml
ideabrd:
  enable: true
  source:
    repoURL: https://github.com/Gin-G/IdeaBRD.git
    targetRevision: main
```

Argo natively runs the Alembic migrate Job (a Helm hook) as a sync hook.

---

## Sign-in & accounts

Log in with **Google** (OIDC) or **GitHub** (OAuth2). Each provider login is an `identities`
row pointing at one `users` record, so a single account can hold both:

- **Auto-link by verified email** — signing in with GitHub whose primary *verified* email matches
  an existing Google account joins them automatically (same board). Unverified emails don't link.
- **Manual connect** — from the **Account** panel (click your name) you can *Connect* the other
  provider even when emails differ, or *Unlink* one (you must keep at least one).
- The GitHub login stores a per-user token used by the repo file sync (see below); the shared
  `GITHUB_TOKEN` PAT is only a fallback for live repo data.

When neither Google nor GitHub is configured, a built-in **dev login** is used (single local user).

## Data model

- **users** — email, name, avatar, and where their board is published
  (`board_repo`, `board_branch`, `board_commit_sha`, `board_published_at`)
- **identities** — (provider `google`/`github`, subject) → user; GitHub token for repo access
- **ideas** — title, notes (markdown), status (`idea`/`active`/`paused`/`done`), progress,
  color, logo, optional `github_repo`, grid position, git sync state (`github_file_sha`,
  `git_synced_at`, `github_logo_path`, `github_logo_sha`), and its board-repo identity
  (`slug`, `rank`)
- **idea_logos** — uploaded/synced tile image bytes, one row per idea
- **todos** — text, done, position (belong to an idea), optional backing GitHub issue
  (`github_issue_number`, `github_issue_url`) and the context mirrored from it
  (`github_issue_labels`, `github_issue_assignee`, `github_issue_comments`)
- **idea_collaborators** — (idea, user, role `editor`/`viewer`, per-user board position)
- **idea_invitations** — pending invites by email (claimed on first login)

Access to an idea is granted to its owner (`ideas.user_id`) plus its collaborators.

## Collaboration

Ideas can be shared with individual collaborators (not the whole board). A shared idea is the
**same record** for everyone, so edits are always consistent.

- **Invite** by email from an idea's *Share* panel (owner only). Pick **editor** (can edit notes,
  todos, progress, status) or **viewer** (read-only). Inviting an email with no account yet
  stores a **pending invite** that auto-activates on their first Google login.
- The shared idea appears on the collaborator's board (flagged "shared", with the owner shown);
  the owner can only delete or manage sharing.
- **Live sync** over a WebSocket (`/api/ws`, authenticated by the session cookie): when any member
  changes an idea or its todos, all connected members get a push and refetch. The in-memory
  connection manager assumes a **single backend replica** (`backend.replicaCount: 1`); scaling out
  would need a shared pub/sub (e.g. Redis).

## Git sync (IDEA.md)

For repo-linked ideas, the idea's details live in an **`IDEA.md`** at the root of the linked
repo — **git is the source of truth**:

```markdown
---
status: active
progress: 60
---

# My idea

<!-- IdeaBRD parses this file… (format rules, stripped on read) -->

Free-form markdown notes.

## Todos

- [x] set up repo
- [ ] build MVP (#12)
```

- **Pull (git wins)** — opening a tile (or *Sync now*) fetches `IDEA.md` via the Contents API;
  if its blob sha changed, the file's title, notes, status, progress and todo checkboxes
  overwrite the database copy and members get a live-sync push. Parsing is lenient, so
  hand-edits on GitHub are fine.
- **Push** — edits made in the app (notes, status, progress, todos) are committed back to
  `IDEA.md` (`… (via IdeaBRD)` commit messages) using the idea owner's GitHub token, falling
  back to the acting user's, then the shared PAT.
- **Opt-in tracking** — linking a repo that already has an `IDEA.md` adopts it automatically.
  If the repo has none, **nothing is committed until the user confirms**: the tile's *Git sync*
  panel prompts "Add IDEA.md to repo" (`POST /api/ideas/{id}/sync?init=true`), and app edits
  stay database-only until then.
- Sync is best-effort: GitHub errors are reported in the tile (`git_sync_error`) and never
  block the app.
- **Push conflicts merge rather than overwrite.** A stale sha means the file changed on GitHub
  since we last read it. The two versions are merged *by meaning* (`app/ideamerge.py`): the
  file we last synced is fetched by its blob sha as the common ancestor, both sides are parsed,
  fields and to-dos are merged — to-dos matched the way `_apply_todos` matches them, by issue
  number where there is one and exact text otherwise — and the result is both pushed and
  written back to the board. Merging the text would not work: the app re-renders the whole
  file, so a line diff sees a rewrite even when nothing changed. Git wins ties, except in
  prose, where a region both sides rewrote keeps both.

### The file format (and how it bites)

Parsing is lenient — it never errors, it just drops what it can't read, which is worse if you
don't know the rules. So **every file IdeaBRD writes carries them**, as an HTML comment plus an
always-present `## Todos` heading: a linked repo is usually edited by someone (or some agent)
who has only the file in front of them, never this README. Comments are stripped on read, so
the block round-trips without showing up on the board.

The block also says what the file is *for*, not just how to write it — that this is the
tracker, that finished work gets ticked off and new work added here rather than in a `TODO.md`
or a plan nobody on the board can see, and that anything worth assigning or writing up at
length should become an issue whose `(#12)` goes on the line. Knowing the syntax and still
keeping your checklist somewhere else leaves the tile just as wrong as a mis-parsed heading.

The parts that silently cost you work:

| Rule | What goes wrong |
|------|-----------------|
| The heading is `## Todos` (or `## To-Dos`), case-insensitive | `## ToDo`, `## TODO`, `## Tasks` don't match — the entire list is parsed as notes instead |
| Only `- [ ]` / `- [x]` lines inside that section survive | `###` sub-headings vanish; a to-do wrapped across two lines is cut at the break |
| A later `## ` heading ends the list | Items after it are notes |
| Prose *outside* the section becomes the tile's notes | Long write-ups are published to the board, not filed away — keep it short |
| Items match existing rows by **exact text**, unless they carry `(#12)` | Rewording a plain to-do is a delete plus an insert, not an edit — a checked item comes back unchecked. Issue-backed ones match on the number, so they survive rewording |
| `status` ∈ `idea`/`active`/`paused`/`done`, `progress` 0-100 | Anything else in frontmatter is ignored |

Render and parse both live in `backend/app/ideafile.py`; the guidance block is the `GUIDANCE`
constant there.

### To-dos backed by issues (`(#12)`)

Any to-do on a repo-linked idea can be **promoted to a GitHub issue** — hover it and hit
*issue*. From then on the issue, not IDEA.md, owns that item:

- **The issue wins.** Every sync reads the repo's issues and applies each linked issue's title
  and open/closed state to its to-do. Rename an issue on GitHub and the to-do renames; close it
  and the box ticks.
- **Ticking closes it.** Toggling a promoted to-do in the app `PATCH`es the issue closed or
  open, and editing its text retitles the issue.
- **The file carries the reference**, as a trailing `(#12)`. That fixes the worst wart of the
  markdown format: plain items are matched between file and board by exact text, so rewording
  one silently replaces it, where a promoted one is matched by number and can be reworded
  freely. Adding `(#12)` to a line by hand adopts the existing to-do rather than duplicating it.
- **Deleting a to-do doesn't close its issue** — it only unbinds. Tidying a tile shouldn't
  reach into someone's issue tracker.

- **The tile shows the issue, not just the sentence.** Labels, the assignee and the comment
  count are mirrored alongside the title and state, so an item on the board carries who has it
  and what it is filed under. All three are read-only here — the board never writes them.
- **Import goes the other way too.** *Import issues* on the to-do list adopts the repo's open
  issues as issue-backed to-dos (`POST /api/ideas/{id}/todos/import`), so a repo that already
  had a hundred issues doesn't arrive at an empty tile. Importing twice is a no-op.

One deliberate limit: a pull that changes an issue-backed to-do **does not commit IDEA.md** —
the file catches up on the next app-side edit. Opening a tile isn't a user action worth a
commit, and the rule that IdeaBRD only writes to a repo when someone asks it to is worth more
than a momentarily stale checkbox.

The pull pages through issues (up to ten pages) rather than reading only the newest hundred,
which used to pin a to-do bound to an old issue to whatever state it already had. Webhooks
(below) remove most of the polling anyway.

Promotion needs no `IDEA.md` opt-in: the click is the opt-in, since nothing reaches the repo
until someone asks. It uses the same token chain as every other push (idea owner's, then the
acting user's, then the shared PAT) and the `repo` scope the GitHub login already requests.
Unlike the best-effort background syncs, a failed promotion is reported to the user — an
explicit action that silently did nothing is worse than an error.

### Tile logos in git (`idea_logo.<ext>`)

The tile image is repo content too, stored at the repo root next to `IDEA.md` as
`idea_logo.png` / `.jpg` / `.gif` / `.webp`:

- **Pull** — every sync lists the repo root and adopts an `idea_logo.*` it finds, caching the
  bytes in `idea_logos` and pointing `logo_url` at `/api/ideas/{id}/logo?v=<blob sha>`. So a
  repo carries its own artwork: link it (or drop the file in by hand) and the tile builds
  itself, for whoever links it. The blob is only downloaded when its sha changes, and images
  over 1MB are skipped.
- **Push** — uploading an image in the app commits it to the repo, subject to the same opt-in
  gate as `IDEA.md`: an untracked repo gets no file. Uploading a different format replaces the
  old file rather than leaving two behind.
- **Delete** — removing the logo in the app commits the file's deletion, and a logo deleted in
  git clears the tile on the next pull. A logo that git never had (uploaded while the repo was
  untracked) is left alone.

## Webhooks (`/api/webhooks/github`)

Everything above pulls, which means a box ticked on GitHub sits unnoticed until someone opens
the tile. The webhook closes that gap: GitHub tells us, the change is written down, and it goes
out over the WebSocket the app is already holding open.

- **`issues` and `issue_comment`** update every to-do bound to that issue — on every board that
  links the repo, since two people may each have a tile pointing at it. A *deleted* issue
  unbinds its to-do rather than deleting it.
- **`push`** re-pulls `IDEA.md` and the logo, but only when the push actually touched them and
  only on the repo's default branch: a tile follows the branch it is read from, and adopting a
  feature branch's `IDEA.md` would show work that isn't merged.
- Everything else is acknowledged and dropped.

The endpoint is public by necessity, so payloads are authenticated with GitHub's HMAC signature
(`X-Hub-Signature-256`) against `GITHUB_WEBHOOK_SECRET`. **Without a secret configured the
endpoint refuses every request** — an unsigned writer into other people's boards is not a thing
to leave running because a value was forgotten. In the chart it is `backend.webhooks: true`
plus `webhook_secret` at `backend.secretPath`.

Point a repository webhook at `https://<fqdn>/api/webhooks/github`, content type
`application/json`, subscribed to *Issues*, *Issue comments* and *Pushes*.

---

## The board repo

A **board repo** holds the whole board as files — one directory per idea, no manifest:

```
.ideabrd                        format version marker
ideas/<slug>/IDEA.md            the idea
ideas/<slug>/idea_logo.png      its tile image, when it has one
```

There is deliberately no `board.yaml`. Order and colour live in each idea's own frontmatter
(`rank`, `color`), so moving a tile rewrites one file instead of the one file every device
shares. `rank` is a **fractional key** compared as text (`app/rank.py`): there is always room
to name a key strictly between two others, so a drag is one write and two devices reordering
different tiles don't conflict.

An idea that has a repository of its own is written here as a **reference** — its rank, colour
and a link — not a copy. Its notes and to-dos are tracked in that repo under its own history,
and a second copy here could only ever drift from it.

- **Set it up** from the *Board repo* panel: create a fresh repo (the app makes it, initialised,
  and publishes into it as its first commit) or link an existing one.
- **Dual-write.** Every mutation — an idea, a to-do, a logo, a reorder, a share — schedules a
  publish in the background (`app/dualwrite.py`). Writes coalesce over a short debounce, so a
  drag is one commit rather than a dozen; an unchanged board publishes nothing at all. Failures
  are recorded and surfaced in the panel rather than swallowed. Postgres stays authoritative:
  git is the copy earning its trust. Set `BOARD_DUAL_WRITE=false` to turn it off.
- **It refuses to publish over commits it didn't make.** A publish builds a tree on the current
  head, so a direct edit to a file the board owns would be silently reverted. If the branch has
  moved since our last publish, nothing is written and the panel offers *Publish over the
  repo's own commits* — with a *Compare* first.
- **Reconcile** (`GET /api/board/reconcile`) lists every idea from both sides and names the
  fields that disagree (`status`, `todos`, `logo`…). Read-only: it is the evidence for cutting
  over to git, not the cutover. It costs no requests for ideas that match, because the desired
  file's git blob sha is computed locally and compared against the sha the tree listing already
  carries.

The repo's README is written by the app and explains the layout to whoever opens it — but only
when there is no README, or the one there carries our sentinel, or it is still the stub GitHub
left on creation. Anything else is somebody's own README and is left where it is.

---

## Android

`android/` packages the same SvelteKit front end as an Android app with Capacitor, and points
it at a **git checkout instead of the API**. There is no server involved once it is set up.

- **The format is ported, not reimplemented.** `android/core` is plain Kotlin — `IdeaFile.kt`,
  `Rank.kt`, `BoardRepo.kt`, `IdeaMerge.kt` — a port of the Python modules of the same names.
  Both renderers are asserted against the golden files in `fixtures/idea-files/`, so a
  divergence fails a build rather than showing up as a board that changes when you change
  device.
- **Sign-in is GitHub's device flow.** An app distributed to people cannot keep a client
  secret, so it shows a short code to type at `github.com/login/device`. The token is stored
  encrypted under an Android Keystore key and never crosses back over the bridge.
- **Sync is fetch, merge, push**, with conflicts in an `IDEA.md` resolved by the same semantic
  merge the server uses. A conflict in anything else is reported, not guessed at.
- **Ideas that live in their own repo are fetched too.** The board records only where such an
  idea is, so the app clones that repository on request and then reads and writes its `IDEA.md`
  directly. Issues behind `(#12)` to-dos are pulled and cached, so an item's title and state
  come from GitHub and ticking its box closes the issue — offline, from the last fetch.
- **Released by GitHub Actions.** `git tag v0.2.0 && git push origin v0.2.0` builds, signs and
  attaches an APK to a GitHub Release (`.github/workflows/android-release.yaml`).

See [`android/README.md`](android/README.md) for how to build it and what it doesn't do yet.

---

## Backups

The CNPG cluster runs a single instance with no replica, so its volume is the only copy of
anything not yet published to git.

- **A nightly `pg_dump`** to a dedicated PVC (`db.backup`, on by default): a CronJob writes
  `ideabrd-<timestamp>.dump` and prunes anything older than `keepDays`. Deliberately
  self-contained — no cloud account, no extra credentials — and restorable with `pg_restore`
  anywhere, including a laptop, which is where a restore usually has to happen when the cluster
  is the thing that broke. The dump is written under a `.partial` name and renamed on success,
  so an interrupted run never leaves a truncated file that looks like a backup. The PVC is
  annotated `helm.sh/resource-policy: keep`.
- **Continuous WAL archiving** to S3-compatible storage for point-in-time recovery
  (`db.backup.objectStore`, off by default): set `destinationPath`, and put
  `access_key_id` / `secret_access_key` in OpenBao at `db.backup.objectStore.secretPath`.

```bash
# restore the latest dump into a scratch database
kubectl -n ideabrd exec -it deploy/ideabrd-backend -- sh -c 'ls -la /backups' # via a debug pod
pg_restore --clean --if-exists -d "$DATABASE_URL" ideabrd-20260824T020000Z.dump
```

---

## Tests

```bash
cd backend && pytest              # the API, git sync, publishing, merging, webhooks
cd android && ./gradlew :core:test  # the Kotlin port, against the shared fixtures
cd frontend && npm run check      # types
```

The backend suite mocks GitHub with `respx`, which means it agrees with whatever the code
believes about the API. That is how the publisher shipped green and could not make its first
commit — GitHub rejects every git data write to a repo with no commits, and no mock had ever
said so. `backend/tests/live/` talks to the real API instead: it creates a throwaway repo,
publishes a board into it, reads it back through a different endpoint than it was written with,
and deletes the repo. It is skipped unless `IDEABRD_GITHUB_TOKEN` is set, and runs weekly in
CI (`.github/workflows/github-live-test.yaml`).

---

## Verifying a deployment

```bash
kubectl -n ideabrd get externalsecrets,cluster,pods,job,ingress
# ESO secrets?   ExternalSecrets show SecretSynced=True
# DB ready?      cluster shows "Cluster in healthy state"
# migrate Job?   ideabrd-backend-migrate shows Completions 1/1
curl -k https://<frontend.fqdn>/api/health      # {"status":"ok",...}
```

Open the host, sign in, create an idea, add to-dos, link a repo (`owner/name`) and confirm the
GitHub panel shows live stars/issues/last-push.

---

## Roadmap / deferred

The board's own to-do list is [`IDEA.md`](IDEA.md) — it is the tracker, and it is what the tile
for this project shows. The larger threads:

- **Cutting over to git.** The database is still authoritative; the repo is dual-written and
  reconcilable, which is what the cutover decision is waiting on. Retiring Postgres also retires
  the chart, the cluster and the collaborator tables — at which point collaboration is git's:
  two people who both link an idea's repo work there by branch and pull request.
- **Collaboration through repo permissions** rather than `idea_collaborators`, once the above
  lands.
- **The Android app on real hardware.** CI builds and packages it and the shared core is well
  covered, but JGit's behaviour on a device — large clones, storage, background limits — has not
  been exercised on one.
- **GitHub Projects v2**: decided against, for reasons worth not rediscovering. See
  [`docs/github-projects-v2.md`](docs/github-projects-v2.md).
