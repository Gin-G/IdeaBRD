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

- **Frontend** — SvelteKit compiled to a static SPA (`adapter-static`), served by nginx.
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

- **users** — email, name, avatar
- **identities** — (provider `google`/`github`, subject) → user; GitHub token for repo access
- **ideas** — title, notes (markdown), status (`idea`/`active`/`paused`/`done`), progress,
  color, logo, optional `github_repo`, grid position, git sync state (`github_file_sha`,
  `git_synced_at`, `github_logo_path`, `github_logo_sha`)
- **idea_logos** — uploaded/synced tile image bytes, one row per idea
- **todos** — text, done, position (belong to an idea), optional backing GitHub issue
  (`github_issue_number`, `github_issue_url`)
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
  block the app. Push conflicts (stale sha) retry once against the current file.

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

Two deliberate limits:

- The pull reads **one page of issues** (100, most recent first). A to-do pointing at an older
  issue keeps the state it had rather than being reported wrong; app-side edits still reach the
  right issue either way. A webhook would remove the polling entirely.
- A pull that changes an issue-backed to-do **does not commit IDEA.md** — the file catches up on
  the next app-side edit. Opening a tile isn't a user action worth a commit, and the rule that
  IdeaBRD only writes to a repo when someone asks it to is worth more than a momentarily stale
  checkbox.

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

- Backups for the Postgres cluster (it runs a single CNPG instance, no replica).
- Richer issue data on the tile (labels, assignee, comment count), and importing a repo's
  existing issues as to-dos rather than only pushing new ones.
- A `/api/webhooks/github` endpoint so an issue closed on GitHub pushes to the tile over the
  existing WebSocket, instead of the state being picked up on the next tile open.
- GitHub **Projects v2**. Deferred on cost, not value: it's GraphQL-only (none of
  `app/github.py` is reusable), it needs the `project` scope added to `github_scope` — which
  every existing GitHub identity would have to re-authorize for, since OAuth tokens don't gain
  scopes — and projects are user/org-owned rather than repo-owned, so an idea would need its own
  project id and a per-project mapping of its Status field's option ids.
