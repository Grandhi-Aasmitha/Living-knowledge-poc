# Living Knowledge POC

Living Knowledge POC is a phased prototype for maintaining canonical system knowledge in Neo4j with a FastAPI backend and React frontend.

Implemented phases:

- Phase 1: FastAPI, React/Vite, Neo4j Community via Podman Compose, and health checks.
- Phase 2: canonical knowledge model, controlled ontology, Neo4j repositories, read-only entity/gap APIs, and TSTVS seed data.
- Phase 3: one human-in-the-loop curation workflow for `MISSING_CONSUMER` gaps using PydanticAI and LangGraph interrupt/resume checkpointing.

## Prerequisites

- Python 3.13
- Node.js and npm
- Podman and Podman Compose
- Azure OpenAI configuration for runtime curation endpoints
- On this machine, Podman may be run from WSL; use the same commands from the WSL shell if Podman is not available in PowerShell.

## Environment setup

Copy the example environment file and set a local Neo4j password before starting services:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `change-this-password` with a local password. The `.env` file is gitignored and must not be committed.

For Phase 3 runtime curation, also set:

```env
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=<local-secret>
AZURE_OPENAI_MODEL=<deployment-or-model-name>
LANGGRAPH_CHECKPOINT_DB=data/langgraph_checkpoints.db
```

Leave Azure values empty when you only need health/entity/gap APIs or automated tests. The backend still starts, and curation endpoints return HTTP 503 until AI is configured.

The canonical `.env` location is the repository root. The backend resolves this file with `pathlib.Path`, so settings do not depend on the shell current working directory.

## Python virtual environment

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Start Neo4j with Podman Compose

Run from the repository root:

```powershell
podman compose --env-file .env up -d neo4j
```

If Podman runs through WSL:

```powershell
wsl sh -lc 'cd /mnt/c/Users/kareddy/ai_sanjeeth_reddy_projects/living-knowledge-poc && podman compose --env-file .env up -d neo4j'
```

These commands target only the project service/container (`neo4j` / `living-knowledge-neo4j`). Do not prune or remove unrelated Podman containers or volumes.

## Seed Phase 2 graph

Run from `backend` with the virtual environment activated:

```powershell
python scripts\seed_phase2.py
```

Expected idempotent summary:

```text
Entities: 3
Claims: 2
Sources: 1
Evidence: 2
Open gaps: 1
```

## Start FastAPI

Run from `backend` with the virtual environment activated:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

FastAPI starts even if Neo4j is temporarily unavailable. The health endpoint reports Neo4j availability dynamically and does not depend on Azure OpenAI.

## Start the frontend

Run from `frontend`:

```powershell
npm install
npm run dev
```

## Run tests

Run from `backend` with dependencies installed:

```powershell
python -m pytest
```

Automated tests use deterministic fake/PydanticAI FunctionModel behavior and do not require Azure credentials.

## Phase 3 curation workflow

1. Ensure Neo4j is running.
2. Run the Phase 2 seed.
3. Configure Azure OpenAI in `.env`.
4. Start FastAPI.
5. Open the frontend at <http://localhost:5173>.
6. In `Knowledge Curator`, click `Resolve` for the open Scheduled Dispatch consumer gap.
7. Answer with:
   ```text
   Scheduler Service
   ```
8. Expected result: the workflow creates/reuses Scheduler Service, creates a confirmed `CONSUMES` claim, stores a HUMAN source and Evidence containing the answer, and resolves the gap.

LangGraph checkpoints are stored in the local SQLite file configured by `LANGGRAPH_CHECKPOINT_DB` and are ignored by Git.

## Local URLs

- Frontend: <http://localhost:5173>
- FastAPI: <http://localhost:8000>
- Swagger/OpenAPI UI: <http://localhost:8000/docs>
- Health API: <http://localhost:8000/api/health>
- Open gaps API: <http://localhost:8000/api/gaps>
- Neo4j Browser: <http://localhost:7474>
- Neo4j Bolt: `bolt://localhost:7687`

## Expected health responses

Neo4j available:

```json
{
  "status": "UP",
  "neo4j": "UP"
}
```

Neo4j unavailable:

```json
{
  "status": "DEGRADED",
  "neo4j": "DOWN"
}
```
