# Living Knowledge POC

Phase 1 creates the infrastructure bootstrap for the Living Knowledge POC. It includes a FastAPI backend, a React/TypeScript Vite frontend, and a Neo4j Community database started with Podman Compose.

This phase intentionally does not implement knowledge-domain functionality, graph models, repositories, document ingestion, LLM integration, LangGraph, PydanticAI, authentication, queues, or observability platforms.

## Prerequisites

- Python 3.13
- Node.js and npm
- Podman and Podman Compose
- On this machine, Podman may be run from WSL; use the same commands from the WSL shell if Podman is not available in PowerShell.

## Environment setup

Copy the example environment file and set a local Neo4j password before starting services:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `change-this-password` with a local password. The `.env` file is gitignored and must not be committed.

The canonical `.env` location is the repository root. The backend resolves this file with `pathlib.Path`, so settings do not depend on the shell current working directory.

## Python virtual environment

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

If `py -3.13` is unavailable but `python` points to Python 3.13:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Start Neo4j with Podman Compose

Run from the repository root:

```powershell
podman compose --env-file .env up -d neo4j
```

These commands target only the project service/container (`neo4j` / `living-knowledge-neo4j`). Do not prune or remove unrelated Podman containers or volumes.

## Start FastAPI

Run from `backend` with the virtual environment activated:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

FastAPI starts even if Neo4j is temporarily unavailable. The health endpoint reports Neo4j availability dynamically.

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

The backend health tests use a fake Neo4j dependency and do not require a real Neo4j instance.

## Neo4j persistence verification

Use the Neo4j Browser or `cypher-shell` against the local database.

1. Create a temporary node:
   ```cypher
   CREATE (:Phase1Test {name: 'persistence-check'});
   ```
2. Verify it exists:
   ```cypher
   MATCH (n:Phase1Test {name: 'persistence-check'}) RETURN count(n) AS count;
   ```
3. Stop the Neo4j container without removing volumes:
   ```powershell
   podman compose stop neo4j
   ```
4. Restart Neo4j:
   ```powershell
   podman compose --env-file .env up -d neo4j
   ```
5. Verify the node still exists with the same `MATCH` query.
6. Delete the temporary node:
   ```cypher
   MATCH (n:Phase1Test {name: 'persistence-check'}) DELETE n;
   ```

## Local URLs

- Frontend: <http://localhost:5173>
- FastAPI: <http://localhost:8000>
- Swagger/OpenAPI UI: <http://localhost:8000/docs>
- Health API: <http://localhost:8000/api/health>
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
