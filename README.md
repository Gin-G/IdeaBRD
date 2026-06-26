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
docker build -t ghcr.io/gin-g/ideabrd-backend:0.1.0 backend
docker build -t ghcr.io/gin-g/ideabrd-frontend:0.1.0 frontend
docker push ghcr.io/gin-g/ideabrd-backend:0.1.0
docker push ghcr.io/gin-g/ideabrd-frontend:0.1.0
```

Adjust `image.registry` / `image.tag` in the chart to match.

---

## Deploying to Kubernetes

### 1. Install the CloudNativePG operator (once per cluster)

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.24/releases/cnpg-1.24.0.yaml
```

### 2. Install the chart

```bash
helm install ideabrd ./chart \
  --namespace ideabrd --create-namespace \
  --set ingress.host=ideabrd.example.com \
  --set image.tag=0.1.0 \
  --set config.cookieSecure=true \
  --set secrets.googleClientId=YOUR_ID \
  --set secrets.googleClientSecret=YOUR_SECRET \
  --set secrets.githubToken=YOUR_PAT
```

What happens:

- A CNPG `Cluster` is created; the operator provisions Postgres and a `*-db-app` secret
  containing the connection `uri` (the backend consumes it directly — the app rewrites the
  scheme to `postgresql+asyncpg`).
- A post-install **migrate Job** runs `alembic upgrade head` (retries while the DB comes up).
- The Ingress routes `/api` to the backend and everything else to the SPA.
- `SESSION_SECRET` is auto-generated and preserved across upgrades if you don't set one.

Set the Google OAuth **redirect URI** to `https://<ingress.host>/api/auth/callback`.

### Useful values

| Value | Default | Notes |
|-------|---------|-------|
| `ingress.host` | `ideabrd.example.com` | Public hostname |
| `ingress.tls.enabled` | `false` | Set true + `ingress.tls.secretName` for HTTPS |
| `config.cookieSecure` | `false` | Set true behind HTTPS |
| `postgres.instances` | `2` | CNPG replicas |
| `postgres.storageSize` | `1Gi` | DB volume size |
| `secrets.existingSecret` | `""` | Reference your own Secret instead of chart-managed |

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
kubectl -n ideabrd get cluster,pods,job,ingress
# DB ready?      cluster shows "Cluster in healthy state"
# migrate Job?   <release>-migrate shows Completions 1/1
curl -k https://ideabrd.example.com/api/health   # {"status":"ok",...}
```

Open the host, sign in, create an idea, add to-dos, link a repo (`owner/name`) and confirm the
GitHub panel shows live stars/issues/last-push.

---

## Roadmap / deferred

- Per-user GitHub OAuth (currently a single configured token for live data).
- Image upload for logos (currently an emoji or image URL).
- Drag-and-drop tile reordering (API + positions already in place).
