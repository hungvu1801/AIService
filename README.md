# AI Dancing (FE_AIDancing)

AI Dancing is a **customer web portal** for running ComfyUI workflows. FastAPI serves the plaza, login, studio forms, and job history. A background worker submits graphs to **ComfyUI on a GPU PC** (usually through a Tailscale SSH tunnel). The browser never talks to ComfyUI.

This repository is the portal and queue. It is **not** ComfyUI itself, not a model trainer, and not a public GPU host. Inference happens only on the GPU machine that already has the nodes and model files each graph names.

```
Browser → this app :8000 (JWT)
              → Postgres (users, jobs, plaza apps)
              → worker → http://127.0.0.1:8188
                    → ssh -N gpu-comfy → GPU ComfyUI :8188
```

HTML pages still load if Postgres or ComfyUI is down. Register, login, and Run need Postgres. Jobs need ComfyUI as well.

---

## What this project is

| It is | It is not |
| --- | --- |
| A FastAPI + Jinja customer site named **AI Dancing** | A ComfyUI fork or custom-node pack |
| A per-account job queue (one GPU job at a time) | A multi-GPU scheduler or cloud marketplace |
| A plaza of **13** studio tools, each bound to a JSON graph under `workflows/` | A generic “paste any workflow” editor |
| JWT auth (register, login, account, optional password-reset email) | OAuth / social login |
| Local uploads under `data/uploads` and outputs under `data/outputs` | A CDN or required S3 pipeline |

The live navigation is **Apps** (plaza), **Studio**, and **Jobs**, plus Log in / Sign up / Account.

The codebase still contains leftover **blog/post** models, templates, and a posts router from an earlier FastAPI scaffold. That posts router is **not** included in `main.py`, and there is no blog in the nav. Do not describe this product as a blog or social network.

---

## User-facing product

1. **Plaza (`/`)** — cards for every seeded app. Titles, descriptions, and studio links come from the `apps` table when Postgres is up, or from the in-code seed catalog if the database is down or empty. Cover images load from `static/plaza/{slug}.png` only when that file exists.
2. **Studio** — a form per tool. The four original tools have dedicated pages. The nine later graphs share `/studio/app/{slug}` and only show the inputs that graph needs (image, second image, audio, prompt, negative, extra text).
3. **Jobs (`/jobs`)** — the signed-in user’s last 50 jobs. Statuses: `queued`, `processing`, `done`, `failed`, `cancelled`. The user can cancel a running/queued job, retry a failed/cancelled job if the original files are still on disk, and download the result (video or still image).
4. **Account** — profile for the current user. Optional avatar upload can use S3 when those env keys are set; otherwise the default local avatar is used.
5. **Password reset** — `/forgot-password` and `/reset-password`. Email is sent only if SMTP settings are configured.

Run always requires a logged-in user. The worker processes **one job at a time** (resume any `processing` job before taking the next `queued` job, highest `priority` then oldest first). Before each new submit it asks ComfyUI to unload models and free VRAM.

Upload limits (enforced by the API): images **15 MB**, video and audio **150 MB**.

---

## Studio catalog (all 13)

There are two wiring styles. Do not mix them up.

**First-party tools** have their own studio page, job endpoint, and inject function.

**Catalog tools** share `/studio/app/{slug}` and `POST /api/jobs/app/{slug}`. Specs live in `app/engine/workflow_apps.py`. The worker loads the listed JSON, converts UI format to ComfyUI API format, patches only the named input nodes, randomizes seeds, and submits.

### First-party

| Plaza title | Slug | Path | Job API | Workflow | User inputs | Output |
| --- | --- | --- | --- | --- | --- | --- |
| Motion Transfer | `motion_transfer` | `/studio` | `POST /api/jobs` | `workflows/motion_transfer.json` | Portrait image + dance video | Video |
| Pixel Art Video | `animatediff` | `/studio/pixel` | `POST /api/jobs/animatediff` | `workflows/animatediff.json` | Video | Video |
| MiniMax H3 | `minimax` | `/studio/minimax` | `POST /api/jobs/minimax` | `workflows/minimaxH3.json` | Start-frame image + optional prompt | Video |
| Wan T2V | `wan_t2v` | `/studio/wan` | `POST /api/jobs/wan` | `workflows/motion_transfer_2.json` | Prompt; optional negative; duration 2 / 4 / 5 / 8 s; size 640×384, 832×480, 1024×576, or 1280×720 | Video |

Wan T2V notes that are true in this repo: playback is forced to **16 fps**; the inject path remaps VAE/UNET names to files this GPU actually has, drops the Lightning LoRA and SeedVR2 upscale nodes, and runs a **single low-noise 14B UNET** so the graph can fit ~32 GB VRAM. MiniMax H3 uses the core node `MiniMaxH3ImageToVideo` and needs **ComfyUI 0.30+** on the GPU. Do not describe MiniMax as a remapped cloud node.

### Catalog (graphs added under `workflows/`)

| Plaza title | Slug | Path | Workflow file | User inputs | Output |
| --- | --- | --- | --- | --- | --- |
| 2D to 3D Upscale | `2d_to_3d` | `/studio/app/2d_to_3d` | `workflows/2D转2.5D转3D.json` | Image (WD14 auto-tags; no required prompt) | Image |
| Cute Doll | `cute_doll` | `/studio/app/cute_doll` | `workflows/Cute+Doll+(flux+pulid).json` | Reference photo; optional VQA prompt template | Image |
| LTX 2.5 Text to Video | `ltx25_t2v` | `/studio/app/ltx25_t2v` | `workflows/文生视频++急速++LTX2.5+音画同出.json` | Required prompt; optional negative | Video (audio+video) |
| Style Reference | `rh_style_ref` | `/studio/app/rh_style_ref` | `workflows/RH+leisure+boat+mat+image+style+reference+image.json` | Content image + style image; optional prompt | Image |
| Logo Poster | `logo_poster` | `/studio/app/logo_poster` | `workflows/迈克尔杰克逊海报.json` | Required subject text; optional logo word | Image |
| Interior Colorize | `interior_colorize` | `/studio/app/interior_colorize` | `workflows/室内设计线稿图上色.json` | Line-art image; optional room-theme prompt | Image |
| Product Background | `product_bg` | `/studio/app/product_bg` | `workflows/[One-click+background+change]+Product+picture+photography.json` | Product photo; optional extra reference | Image |
| Image Matting | `image_matting` | `/studio/app/image_matting` | `workflows/image+matting.json` | Photo | Image |
| InfiniteTalk | `infinitetalk` | `/studio/app/infinitetalk` | `workflows/infinitetalk+digital+human.json` | Portrait + speech audio; optional prompt/negative | Video |

Style Reference calls a **RunningHub Midjourney V8.1 node**. It is not local SD/Flux inference unless that RH node is already configured on the GPU ComfyUI.

Every catalog graph still needs **its custom nodes and model files on that ComfyUI**. If a class is missing, the job fails with the missing node names (not a silent skip).

Plaza seed rows are inserted **only when the slug is missing**. Later title/description edits in Postgres are kept.

---

## How a job runs

1. The signed-in user submits a studio form. Files and text are stored under `data/uploads/{job_id}/`. For prompt-only or catalog jobs, `prompt.txt` (and optional `negative.txt` / `extra.txt`) sit in that folder. The `jobs` row records `tool` (the slug), paths, and status `queued`.
2. The worker picks at most one job, sets `processing`, and calls ComfyUI `/free` (unload models).
3. Inputs are uploaded to ComfyUI’s input folder. The matching inject function builds an API prompt: UI JSON (`nodes` + `links`) is converted when needed; combo widget values are remapped to the exact strings `/object_info` lists (Windows backslash vs slash).
4. The worker `POST`s `/prompt`, stores `prompt_id`, and waits until ComfyUI reports **completed** (not a partial VHS preview).
5. Output is downloaded from history: video apps prefer `.mp4` / VHS combine; image apps accept `SaveImage` PNG/JPG. Filename-prefix hints (for example `wananimate_output`, `LTX-2.5_t2v`, `infinitetalk`, `TensorArt`) pick the right file when several exist.
6. The file is saved under `data/outputs/{job_id}{suffix}` and the job becomes `done`. Errors are stored on the row (truncated). Cancel interrupts ComfyUI and marks `cancelled`. Retry re-queues the same files.

If the process restarts while a job is `processing`, the worker tries to finish from ComfyUI history or leftover output files. If both are gone, the user retries from Jobs.

---

## HTTP surface (mounted)

**Pages:** `/` `/studio` `/studio/pixel` `/studio/minimax` `/studio/wan` `/studio/app/{slug}` `/jobs` `/login` `/register` `/account` `/forgot-password` `/reset-password`

**APIs actually included in `main.py`:**

| Method | Path | Auth | Role |
| --- | --- | --- | --- |
| POST | `/api/users` | No | Register |
| POST | `/api/users/token` | No | Login (OAuth2 password form) → JWT |
| GET | `/api/users/me` | Yes | Current user |
| PATCH | `/api/users/me/password` | Yes | Change password |
| POST | `/api/users/forgot-password` | No | Start reset |
| POST | `/api/users/reset-password` | No | Finish reset |
| GET | `/api/apps` | No | Live plaza rows |
| POST | `/api/jobs` | Yes | Motion Transfer |
| POST | `/api/jobs/animatediff` | Yes | Pixel Art |
| POST | `/api/jobs/minimax` | Yes | MiniMax H3 |
| POST | `/api/jobs/wan` | Yes | Wan T2V |
| POST | `/api/jobs/app/{slug}` | Yes | Catalog tool |
| GET | `/api/jobs` | Yes | List mine (50) |
| GET | `/api/jobs/{id}` | Yes | One job |
| POST | `/api/jobs/{id}/cancel` | Yes | Cancel |
| POST | `/api/jobs/{id}/retry` | Yes | Retry failed/cancelled |
| GET | `/api/jobs/{id}/download` | Yes | File |

JWT: HS256, `SECRET_KEY`, default lifetime **1440 minutes**. Tokens are stored in the browser and sent as `Authorization: Bearer …`.

---

## Data model (Postgres)

Tables are created with SQLAlchemy `create_all` on startup. There is **no Alembic migration step** for a first boot (Alembic may appear in `requirements.txt` from the old scaffold; this app does not use it to ship schema).

| Table | Purpose |
| --- | --- |
| `users` | Username, email, password hash, optional avatar filename |
| `jobs` | Per-user queue: `tool` slug, status, input paths, `prompt_id`, output path, error, priority |
| `apps` | Plaza metadata: slug, title, description, engine label, route name, media class, live flag, sort order |
| `password_reset_tokens` | Hashed reset tokens |
| `posts` | Leftover blog table; not part of the live plaza product |

Default Docker database name `blog` is historical (same scaffold). It is still the database name in `docker-compose.yml`.

---

## What you need

| Piece | Where | Required for |
| --- | --- | --- |
| Python **3.12+** | App PC | Always |
| PostgreSQL | App PC via Docker Compose (or any host in `DATABASE_URL`) | Login and jobs |
| This repo + `.env` | App PC | Always |
| ComfyUI + models + custom nodes | GPU PC | Running studio jobs |
| Tailscale + SSH tunnel | Both PCs | Reaching ComfyUI from the app PC |

GPU wiring (OpenSSH, `Host gpu-comfy`, `administrators_authorized_keys`) is in [docs/tailscale-two-machines.md](docs/tailscale-two-machines.md). That doc is generic: do not copy machine-specific Tailscale IPs, Windows usernames, or disk paths from a chat into it.

---

## 1. Get the code

```bat
git clone https://github.com/hungvu1801/AIService.git .
cd <repo-directory>
```

`<repo-directory>` is the folder Git created (or the copy of the project you already have). All later commands run from there.

---

## 2. Python environment

PowerShell on the **app PC**, from `<repo-directory>`:

```bat
python --version
```

You want 3.12 or newer. Then:

```bat
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Later sessions, from the same folder:

```bat
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
| --- | --- |
| Database | `blog` |
| User / password | `bloguser` / `blogpass` |
| Data volume | Docker volume `aidancing_pgdata` |

Match `.env`:

```env
DATABASE_URL=postgresql+psycopg://bloguser:blogpass@localhost/blog
```

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

If port 5432 is already in use, either stop that service or change the left-hand port in `docker-compose.yml` (for example `"5433:5432"`) and the port in `DATABASE_URL`.

Native Postgres without Docker still works: create user `bloguser` and database `blog`, then point `DATABASE_URL` at that instance.

---

## 4. Environment file

```bat
copy .env.example .env
```

Edit `.env`. Minimum:

```env
SECRET_KEY=replace-with-a-long-random-string
DATABASE_URL=postgresql+psycopg://bloguser:blogpass@localhost/blog
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
- Catalog workflow paths are **not** env vars. They are hardcoded next to each slug in `app/engine/workflow_apps.py`.

---

## 5. Start the web app

Always:

```bat
python main.py
```

Not `python run main.py`. On Windows this sets `WindowsSelectorEventLoopPolicy` and runs Uvicorn with reload on `127.0.0.1:8000`.

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
| --- | --- |
| `can't open file '...\\run'` | Use `python main.py` |
| Home page 500 / `jobs_page` | App routes; restart after pulling latest `main.py` |
| Login timeout / `connection timeout expired` | `docker compose up -d`; check `DATABASE_URL` |
| New plaza cards missing after a pull | Restart `python main.py` so `seed_apps` can insert missing slugs |
| Job queued forever | Tunnel + ComfyUI; `curl http://127.0.0.1:8188/system_stats` on the app PC |
| ComfyUI `missing_node_type` | That node is not installed on the GPU (or ComfyUI is too old) |
| ComfyUI `value_not_in_list` | Model filename is not in `models/` on the GPU |
| CUDA OOM | Restart ComfyUI with `--lowvram`; quit the process fully after OOM |
| MiniMax job fails on node type | GPU ComfyUI is older than 0.30; update ComfyUI, then retry |

---

## Project layout

```
main.py                      # Uvicorn entry, HTML routes, lifespan (DB seed + worker)
app/core/                    # settings, SQLAlchemy models, JWT auth, plaza seed
app/routers/                 # /api/users, /api/jobs, /api/apps
app/engine/comfy.py          # upload, /prompt, poll history, download image or video
app/engine/workflow_convert.py  # UI→API convert, combo remap, first-party inject
app/engine/workflow_apps.py  # catalog of the nine shared-studio graphs
app/engine/worker.py         # one-at-a-time job loop
workflows/                   # ComfyUI JSON graphs (UI export)
templates/ static/           # plaza, studio, jobs, auth UI
data/                        # uploads and outputs (created at runtime)
docs/tailscale-two-machines.md
```

---

## Facts an essay must not invent

- Customers do **not** open ComfyUI or port 8188. Only this backend does.
- There is **one** shared `COMFYUI_BASE_URL` (default `http://127.0.0.1:8188`), not a pool of engines.
- The worker runs **one** ComfyUI prompt at a time.
- Python must be **3.12+**. On Windows, start with `python main.py` so the selector event loop is set.
- Schema is `create_all` + slug-only seed. Do not claim Alembic is how this app ships tables.
- Do not list real Tailscale IPs, SSH usernames, or GPU disk paths. Those belong on the machines, not in this file.
- Do not describe unused blog templates as a shipped feature.
- Do not claim every plaza card has a poster PNG; only slugs with a file in `static/plaza/` show a photo.
- Do not claim catalog apps work without the matching custom nodes on the GPU ComfyUI.
- InfiniteTalk’s studio default prompt is **A person is speaking.**
