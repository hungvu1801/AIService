# AI Dancing (FE_AIDancing)

Customer portal for AI video jobs. FastAPI serves the plaza, login, and job queue. A background worker submits graphs to **ComfyUI** on a GPU PC (usually through a Tailscale SSH tunnel). The browser never talks to ComfyUI.

```
Browser → this app :8000 (JWT)
              → Postgres (users + jobs)
              → worker → http://127.0.0.1:8188
                    → ssh -N gpu-comfy → GPU ComfyUI :8188
```

Pages still load if Postgres or ComfyUI is down. Register, login, and Run need Postgres. Jobs need ComfyUI as well.

---

## What you need

| Piece | Where | Required for |
|---|---|---|
| Python **3.12+** | App PC | Always |
| PostgreSQL | App PC via Docker Compose (or any host in `DATABASE_URL`) | Login and jobs |
| This repo + `.env` | App PC | Always |
| ComfyUI + models | GPU PC | Running studio jobs |
| Tailscale + SSH tunnel | Both PCs | Reaching ComfyUI from the app PC |

GPU wiring (OpenSSH, `gpu-comfy`, `administrators_authorized_keys`) is in [docs/tailscale-two-machines.md](docs/tailscale-two-machines.md).

---

## 1. Get the code

```bat
cd F:\Hung\MyProjects
git clone <this-repo-url> FE_AIDancing
cd FE_AIDancing
```

Or use the folder you already have.

---

## 2. Python environment

PowerShell on the **app PC**:

```bat
cd F:\Hung\MyProjects\FE_AIDancing
python --version
```

You want 3.12 or newer. Then:

```bat
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Later sessions only need:

```bat
cd F:\Hung\MyProjects\FE_AIDancing
.\.venv\Scripts\activate
```

---

## 3. PostgreSQL (Docker)

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) on the app PC. From the repo root:

```bat
docker compose up -d
docker compose ps
```

Wait until `aidancing-postgres` is healthy. This starts Postgres 16 on `127.0.0.1:5432` with:

| | |
|---|---|
| Database | `aidancing` |
| User / password | `aidancing` / `aidancing` |
| Data volume | Docker volume `aidancing_pgdata` |

Match `.env`:

```env
DATABASE_URL=postgresql+psycopg://aidancing:aidancing@127.0.0.1:5432/aidancing
```

Tables are created on app startup (`create_all`). You do not run Alembic for a first boot.

Useful commands:

```bat
docker compose logs -f postgres
docker compose down
```

`down` stops the container and keeps the volume. To wipe the database as well:

```bat
docker compose down -v
```

If Postgres is stopped, the plaza still opens and the log says `Database not ready (pages still load)`. Login and `/api/jobs` will fail until it is up.

If port 5432 is already in use (a local Postgres install), either stop that service or change the left-hand port in `docker-compose.yml` (for example `"5433:5432"`) and the port in `DATABASE_URL`.

Native Postgres without Docker still works: create user `aidancing` and database `aidancing`, then point `DATABASE_URL` at that instance.

---

## 4. Environment file

```bat
copy .env.example .env
```

Edit `.env`. Minimum:

```env
SECRET_KEY=replace-with-a-long-random-string
DATABASE_URL=postgresql+psycopg://aidancing:aidancing@127.0.0.1:5432/aidancing
FRONTEND_URL=http://localhost:8000

COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=workflows/motion_transfer.json
COMFYUI_ANIMATEDIFF_WORKFLOW_PATH=workflows/animatediff.json
COMFYUI_MINIMAX_WORKFLOW_PATH=workflows/minimaxH3.json
COMFYUI_WAN_T2V_WORKFLOW_PATH=workflows/motion_transfer_2.json
DATA_DIR=data
```

- `SECRET_KEY` — any long random string (JWT signing). Do not commit `.env`.
- `DATABASE_URL` — must use the `postgresql+psycopg://` prefix (async psycopg).
- `COMFYUI_BASE_URL` — leave as localhost if you use `ssh -N gpu-comfy`. Only change it if ComfyUI is reachable at another URL.
- Mail and S3 keys in `.env` are optional. Password-reset email needs SMTP; avatars can stay local.

---

## 5. Start the web app

Always:

```bat
python main.py
```

Not `python run main.py`. On Windows this sets `WindowsSelectorEventLoopPolicy` and runs Uvicorn with reload.

Wait for:

```text
Uvicorn running on http://127.0.0.1:8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) → **Sign up** → **Log in**.

Uploads and outputs go under `data/uploads` and `data/outputs`.

---

## 6. Connect ComfyUI (needed to Run jobs)

On the **GPU PC**: start ComfyUI (see the Tailscale doc for `--lowvram`). Check:

```bat
curl http://127.0.0.1:8188/system_stats
```

On the **app PC**: Tailscale connected, then:

```bat
ssh -N gpu-comfy
```

Leave that window open. In another terminal:

```bat
curl http://127.0.0.1:8188/system_stats
```

You should see the GPU JSON. Then start `python main.py` if it is not already running.

First-time SSH setup is the whole of [docs/tailscale-two-machines.md](docs/tailscale-two-machines.md).

---

## Studio apps

| Plaza | Path | Job API | Workflow file |
|---|---|---|---|
| Motion Transfer | `/studio` | `POST /api/jobs` | `workflows/motion_transfer.json` |
| Pixel Art Video | `/studio/pixel` | `POST /api/jobs/animatediff` | `workflows/animatediff.json` |
| MiniMax H3 | `/studio/minimax` | `POST /api/jobs/minimax` | `workflows/minimaxH3.json` |
| Wan T2V | `/studio/wan` | `POST /api/jobs/wan` | `workflows/motion_transfer_2.json` |

The GPU ComfyUI must have the **nodes and model files** each graph names. MiniMax H3 needs ComfyUI **0.30+**. Wan T2V currently remaps missing Lightning files and uses a smaller single-UNET graph so it can fit ~32 GB VRAM.

Jobs: `/jobs` (poll, download, cancel). One job at a time.

---

## Daily start order

1. Tailscale on both PCs (`tailscale status`).
2. Postgres: `docker compose up -d` (wait until healthy).
3. ComfyUI on the GPU.
4. App PC: `ssh -N gpu-comfy`.
5. App PC: `.\.venv\Scripts\activate` then `python main.py`.
6. Browser: `http://127.0.0.1:8000`.

---

## If something fails

| What you see | What to do |
|---|---|
| `can't open file '...\\run'` | Use `python main.py` |
| Home page 500 / `jobs_page` | App routes; restart after pulling latest `main.py` |
| Login timeout / `connection timeout expired` | `docker compose up -d`; check `DATABASE_URL` |
| Job queued forever | Tunnel + ComfyUI; `curl http://127.0.0.1:8188/system_stats` on the app PC |
| ComfyUI `missing_node_type` | That node is not installed on the GPU (or ComfyUI is too old) |
| ComfyUI `value_not_in_list` | Model filename is not in `models/` on the GPU |
| CUDA OOM | Restart ComfyUI with `--lowvram`; quit the process fully after OOM |

---

## Project layout (short)

```
main.py                 # Uvicorn entry, HTML routes
app/core/               # config, DB, auth, Job model
app/routers/            # /api/users, /api/jobs
app/engine/             # ComfyUI client, workflow inject, worker
workflows/              # ComfyUI JSON graphs
templates/ static/      # plaza and studio UI
data/                   # uploads and outputs (created at runtime)
docs/tailscale-two-machines.md
```
