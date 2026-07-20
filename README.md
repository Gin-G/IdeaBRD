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
pytest                                   # 9 tests
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

To enable **GitHub login**, create a GitHub OAuth app (callback
`https://<fqdn>/api/auth/github/callback`), add `github_client_id` + `github_client_secret` to
`ideabrd/backend` in OpenBao, and set `backend.githubOAuth: true` in `values.yaml`. (The flag
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
  `git_synced_at`)
- **todos** — text, done, position (belong to an idea)
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

Free-form markdown notes.

## Todos

- [x] set up repo
- [ ] build MVP
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

- Per-user GitHub OAuth (currently a single configured token for live data).
- Image upload for logos (currently an emoji or image URL).
- Drag-and-drop tile reordering (API + positions already in place).
