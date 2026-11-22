# Living Knowledge POC

Living Knowledge POC is a phased prototype for maintaining canonical system knowledge in Neo4j with a FastAPI backend and React frontend.

Implemented phases:

- Phase 1: FastAPI, React/Vite, Neo4j Community via Podman Compose, and health checks.
- Phase 2: canonical knowledge model, controlled ontology, Neo4j repositories, read-only entity/gap APIs, and TSTVS seed data.
- Phase 3: human-in-the-loop curation workflow using LangGraph interrupt/resume checkpointing.
- Phase 3.1: provider-neutral `StructuredAIClient` with Tabnine CLI by default and optional Azure OpenAI/PydanticAI when explicitly configured.
- Phase 4: document ingestion, structured knowledge extraction, and contextual entity resolution for PDF, DOCX, PPTX, TXT, and Markdown uploads.
- Phase 5: graph explorer with provenance views.
- Phase 6: automatic knowledge gap detection.
- Phase 8: conflict detection and human resolution.
- Phase 9: read-only Knowledge Assistant with typed bounded planning, deterministic retrieval, evidence-backed answers, citation validation, and deterministic golden evaluation.
- Team learning: durable source observations, identity questions, human decisions, recovered claims, alias provenance, source-version reconciliation, and longitudinal integration checks.
- Uploaded claim review: a namespace-scoped queue of proposed file claims with source evidence, human confirm/reject decisions, recorded reasons, and a way to reopen a decision.

This POC is for local development/demo use only. Set `APP_PASSWORD` in the ignored `.env` to protect the knowledge API with a shared password. The browser keeps the session in an HTTP-only, same-site cookie; write requests also check their origin. This is a shared local login, not individual accounts or a public deployment security model.

For current macOS/Linux and Windows startup instructions, AI provider configuration, verification, and troubleshooting, see [SETUP.md](SETUP.md).

## Prerequisites

- Python 3.13
- Node.js and npm
- Podman and Podman Compose
- Authenticated Tabnine CLI (default) or Azure OpenAI for AI-backed features. Explicit document relationships can also be ingested offline with `AI_PROVIDER=local_rules`; see [SETUP.md](SETUP.md).
- On this machine, Podman may be run from WSL; use the same commands from the WSL shell if Podman is not available in PowerShell.

## Environment setup

Copy the example environment file and set a local Neo4j password before starting services:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `change-this-password` with a local password. Also set `APP_PASSWORD` to a separate strong shared password. The `.env` file is gitignored and must not be committed. Open the frontend and sign in with `APP_PASSWORD` before using a knowledge feature.

If choosing Azure OpenAI instead of the default Tabnine CLI, also set:

```env
AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=<local-secret>
AZURE_OPENAI_MODEL=<deployment-or-model-name>
LANGGRAPH_CHECKPOINT_DB=data/langgraph_checkpoints.db
ENTITY_RESOLUTION_AUTO_MATCH_THRESHOLD=0.9
ENTITY_RESOLUTION_MAX_CANDIDATES=5
```

Leave Azure values empty when using Tabnine, local rules, or when you only need existing knowledge and automated tests. Set `AI_PROVIDER=local_rules` to upload explicit relationships without AI credentials; assistant and AI-backed curation remain unavailable in this mode. If the selected AI provider cannot initialize, the backend still starts but AI-backed endpoints return HTTP 503. See [SETUP.md](SETUP.md) for all modes.

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
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
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

Run integration tests against a disposable Neo4j instance using the `NEO4J_*` environment settings. They create and clean up fixture data. The ingestion fixture cleanup is scoped to its own documents and entities and preserves the shared upload source.

## Contextual entity resolution

During document ingestion, extracted entity mentions are resolved against active entities in the same namespace before new graph nodes are created. The application generates a bounded set of lexically plausible, type-compatible candidates and asks the configured structured AI provider to choose `MATCH`, `CREATE`, or `NEEDS_REVIEW`.

High-confidence matches reuse the canonical entity and store the observed name as an alias. Low-confidence or ambiguous matches are returned in `unresolved_terms`, and claims that depend on those unresolved entities are deferred instead of being attached to a guessed node. The AI may only select candidate IDs supplied by the application and never receives direct Neo4j access.

After an upload, the UI shows a learning report with new and recognized entities, aliases learned, new facts, and unresolved terms. Filter the report by outcome and expand an AI decision to read its explanation. The upload summary clears on reload, while **Questions for the team** loads saved identity questions from Neo4j. Choose the correct existing entity or establish a separate entity, explain the decision, and the system remembers the name and applies its waiting claims. Recorded decisions are also browsable and can safely be re-applied after a failed materialization.

`LearningBatch` preserves extracted proposals and source context; `EntityMention` preserves decisions and human reasons; `AliasBinding` reserves learned names and records their provenance. Human identity confirmation does not automatically confirm claims extracted from files. Source files are identified within a team namespace. Failed ingestion does not mark the file current; retries reuse saved proposals. Publishing a new version deactivates the prior version's evidence without deleting history. Current graph queries, gap/conflict scans, and assistant retrieval respect evidence activity; assistant retrieval also respects claim validity dates.

The **Review uploaded claims** section lists proposed claims with current file evidence in the selected namespace. Select a claim to inspect its source excerpt and document version, then enter a reviewer name and reason to **Confirm** or **Reject** it. Decisions are recorded in Neo4j; reviewed claims can be reopened for another review. Confirmed claims appear as confirmed in the graph and can support a confirmed Assistant answer when no cited claim is proposed and no gap or conflict is open. Rejected claims are excluded from the default graph and Assistant retrieval. Reuploading the same rejected fact does not silently restore it. The shared local password protects the API, but reviewer names are still self-reported because there are no individual accounts.

Newly extracted, source-backed file claims are confirmed automatically by default, as configured by `AUTO_CONFIRM_FILE_CLAIMS=true`. This trusts the AI extraction without a human checking each fact. Existing rejected claims and claims reopened for review retain their prior decisions. Set `AUTO_CONFIRM_FILE_CLAIMS=false` in the ignored local `.env` to require manual review instead.

`EXTRACTION_AUDIT_ENABLED=true` makes a second structured AI pass over each chunk for relations the first pass missed. The audit merges additional source-backed claims and rejects evidence not copied from the document. This increases upload time and AI usage; it improves recall but cannot guarantee complete extraction. Set it to `false` to skip the extra pass.

`PDF_OCR_ENABLED=true` enables image-only PDF reading with the Azure OpenAI provider. The upload converts up to four embedded images per page into bounded PNGs and asks the configured vision-capable model to transcribe them. OCR is limited to 20 PDF pages per upload, adds AI usage, and may misread text; the extracted claims still retain their transcribed evidence. Set it to `false` to disable OCR.

The **Review possible duplicate names** section suggests similar names with the same entity type in the selected namespace. You can also choose a pair manually when spelling differs. A person chooses which entity to keep and records a reason before merging. The merge retires the duplicate, adds its names as aliases, reconnects its claims, gaps, saved identity resolutions, and learning bindings, and keeps evidence and a merge audit record. Similarity only creates suggestions; no merge occurs without approval. Older file documents without a namespace are treated as belonging to the original `tstvs` namespace. Legacy knowledge with no processing-status or evidence-activity field keeps its previous behavior until a new version is published.

Select **Reprocess even if unchanged** when uploading an older file to apply the new learning policy. This creates a new processing revision, learns against current team knowledge, and preserves earlier evidence. Normal unchanged uploads continue to skip extraction.

The current local POC serializes same-document uploads within one backend process. Multi-process ingestion needs a durable queue and distributed document lock before scaling out.

Research and architectural decisions, checked against current primary sources, are in [team-learning-research.md](docs/team-learning-research.md).

The graph refreshes after a successful upload or gap resolution. Node details show alternate names, and graph search recognizes aliases as well as canonical names.

## Phase 3 curation workflow

1. Ensure Neo4j is running.
2. Run the Phase 2 seed.
3. Configure Tabnine CLI or Azure OpenAI in `.env` as described in [SETUP.md](SETUP.md).
4. Start FastAPI.
5. Open the frontend at <http://localhost:5173>.
6. In `Knowledge Curator`, click `Resolve` for the open Scheduled Dispatch consumer gap.
7. Answer with:
   ```text
   Scheduler Service
   ```
8. Expected result: the workflow creates/reuses Scheduler Service, creates a confirmed `CONSUMES` claim, stores a HUMAN source and Evidence containing the answer, and resolves the gap.

LangGraph checkpoints are stored in the local SQLite file configured by `LANGGRAPH_CHECKPOINT_DB` and are ignored by Git.

## Application lifecycle assessment

The **Migration and retirement assessment** panel uses a separate LangGraph workflow. Select the same namespace used for your uploaded documents, enter the exact source application or service name shown in the graph, optionally enter a target, and choose **Start new assessment**. The workflow reads current claims, source excerpts, open gaps, and conflicts from Neo4j. It evaluates source dependencies, target discovery, capability parity, options, security and nonfunctional requirements, then a recommendation. Findings remain a draft until an architect reviews them.

When a detail is missing, the workflow pauses and shows a question. Answer it (or say `unknown`) to resume the same assessment. Reviewers can approve a draft or request a revision with comments. The assessment ID is stored in the browser for the active namespace, and the LangGraph checkpoint lets the backend restore the assessment after refresh or restart. Clarifications are saved in assessment state; they do not automatically become facts in Neo4j.

The API exposes `POST /api/assessments`, `GET /api/assessments/{id}`, `POST /api/assessments/{id}/answers`, and `POST /api/assessments/{id}/review`. The configured AI provider must be `azure_openai` or `tabnine_cli`; local rules mode supports document uploads only. The current POC uses a shared local password, so reviewer names are self reported. Source code ingestion, embeddings, SSO, PDF reports, and target capability catalogs described in the LLD are not yet connected. Missing target or policy evidence should appear as partial or in progress, not as a fabricated recommendation.

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
