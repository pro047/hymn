# Hymn Python Backend

Lightweight FastAPI starter with a health endpoint and root greeting.

## Getting started
1. Create a virtual environment (example):  
   `python -m venv .venv && source .venv/bin/activate`
2. Install dependencies:  
   `pip install -r requirements.txt`
3. Run the dev server:  
   `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir src`

## Docker
- Production: `docker build -t hymn-api:prod -f Dockerfile .` → `docker run --rm -p 8000:8000 hymn-api:prod`
- Development (reload): `docker build -t hymn-api:dev -f Dockerfile.dev .`  
  Run with live code: `docker run --rm -p 8000:8000 -v $(pwd)/src:/app/src hymn-api:dev`
  (dev image uses `--reload`)

## Environment
- Prod: copy `.env.example` → `.env` and set values (include `IMAGE` = ECR URI).
- Dev: copy `.env.dev.example` → `.env.dev` and set values (APP_ENV=development).
- Keys:
  - `APP_ENV`
  - `AWS_REGION`
  - `S3_BUCKET`
  - `DATABASE_URL` (e.g., `postgresql://appuser:password@rds-endpoint:5432/postgres`)
  - `IMAGE` (e.g., `<account>.dkr.ecr.ap-northeast-2.amazonaws.com/hymn-dev-api:<tag>`)
- `docker-compose.yml` reads `.env`, `docker-compose.dev.yml` reads `.env.dev`.

## Available endpoints
- `GET /health` → `{"status": "ok"}`
- `GET /` → `{"message": "Hello from Hymn backend"}`

## Project layout
- `src/app/main.py` – FastAPI application entrypoint
- `requirements.txt` – Python dependencies
- `.gitignore` – Ignores venvs, caches, IDE files
- `Dockerfile` / `.dockerignore` – Container build context
