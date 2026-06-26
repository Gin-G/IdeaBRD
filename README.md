# IdeaBRD

A personal **idea board**. Log in with Google, get a grid of tiles — one per idea — and click
into any tile for notes, a to-do list, progress tracking, and live GitHub data for repo-linked
ideas. Built to run on Kubernetes.

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

```bash
docker build -t docker.io/ncging/ideabrd-backend:latest backend
docker build -t docker.io/ncging/ideabrd-frontend:latest frontend
docker push docker.io/ncging/ideabrd-backend:latest
docker push docker.io/ncging/ideabrd-frontend:latest
```

Set the matching `backend.container.image` / `frontend.container.image` in `chart/values.yaml`.

---

## Deploying to Kubernetes

The chart (`chart/`) follows the same conventions as the ratetheslopes deployment:
**External Secrets Operator + OpenBao** for all secrets, **CloudNativePG** bootstrapped from
ESO-provided credentials, per-service ingresses (cert-manager + external-dns), and everything
driven from `chart/values.yaml`. It is intended to be deployed by **Argo CD** (see
`argocd/ideabrd-application.yaml`).

### Cluster prerequisites

- **CloudNativePG operator** (provides the `Cluster` CRD)
- **External Secrets Operator** (provides `SecretStore` / `ExternalSecret`)
- **OpenBao/Vault** reachable at `openbao.openbao.svc.cluster.local:8200`, plus an
  `openbao-credentials` Secret (key `OPENBAO_TOKEN`) in the `ideabrd` namespace
- cert-manager `ClusterIssuer` `letsencrypt-cloudflare` and external-dns (for the ingresses)

### OpenBao secret paths

The chart's ExternalSecrets read from these KV paths (override via `values.yaml`):

| Path (`kv/...`) | Properties |
|-----------------|------------|
| `ideabrd/db`      | `dbsu`, `dbsupassw` (superuser), `dbuser`, `dbpassw` (app user) |
| `ideabrd/backend` | `session_secret`, `google_client_id`, `google_client_secret`, `github_token` |

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
- Two Ingresses on `frontend.fqdn` route `/api` → backend and `/` → SPA, with TLS via cert-manager.

Set the Google OAuth **redirect URI** to `https://<frontend.fqdn>/api/auth/callback`.

### Key values

| Value | Default | Notes |
|-------|---------|-------|
| `frontend.fqdn` | `ideabrd.example.com` | Public hostname (both ingresses + OAuth redirect) |
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

## Data model

- **users** — `google_sub`, email, name, avatar
- **ideas** — title, notes (markdown), status (`idea`/`active`/`paused`/`done`), progress,
  color, logo, optional `github_repo`, grid position
- **todos** — text, done, position (belong to an idea)

All idea/todo endpoints are scoped to the logged-in user.

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
