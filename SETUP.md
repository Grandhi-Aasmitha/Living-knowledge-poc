# Local setup and run guide

This guide runs the Living Knowledge POC locally: Neo4j stores knowledge, FastAPI serves the API, and React/Vite provides the UI. Run the backend and frontend in separate terminals.

This is a development POC, not a production deployment. Set a shared `APP_PASSWORD` for the knowledge API and keep services private. The supplied Compose file publishes Neo4j ports on the host, so use an appropriate local firewall and do not expose them to untrusted networks. Uploaded text and questions may be sent to your selected AI provider; use documents approved for that provider.

## 1. Prerequisites

- Git.
- Python **3.13** (the backend requires `>=3.13,<3.14`).
- Node.js and npm. The checked-in frontend lockfile requires Node **20.19+ within version 20**, or **22.12+**.
- Podman with Compose support, or Docker with Compose support, for Neo4j.
- For AI features: an installed, authenticated Tabnine CLI **or** configured Azure OpenAI access. You do not need both.

Check your tools:

```sh
git --version
python3.13 --version
node --version
npm --version
podman compose version
```

On Windows PowerShell, use `py -3.13 --version` instead of `python3.13 --version`. If using Docker, check `docker compose version` instead. Start your container runtime before continuing. If Podman uses a virtual machine, inspect `podman machine list`, initialize a machine only if none exists, then start it. When using WSL, run the setup commands inside the same WSL environment rather than mixing Windows and Linux virtual environments.

## 2. Get the repository and configure the environment

For a new checkout:

```sh
git clone https://github.com/sanjeethreddy/living-knowledge-poc.git
cd living-knowledge-poc
```

For an existing checkout, open a terminal at its root instead. All commands below name their working directory.

Copy the environment template **only if `.env` does not already exist**. Do not overwrite an existing configuration.

macOS/Linux, from the repository root:

```sh
cp .env.example .env
```

Windows PowerShell, from the repository root:

```powershell
Copy-Item .env.example .env
```

Edit the root `.env` and replace `change-this-password` with a local Neo4j password:

```dotenv
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=replace-with-your-local-password
NEO4J_DATABASE=neo4j
FRONTEND_ORIGIN=http://localhost:5173
APP_PASSWORD=replace-with-a-separate-strong-password
```

Keep the remaining template settings unless you need to customize them. `.env` is ignored by Git; never commit credentials. The backend reads this root file regardless of the terminal's working directory. Environment variables already exported in the shell take precedence, so check them if settings seem unexpected.

### Choose a document extraction mode

**Option A — Tabnine CLI (default)**

Install and authenticate the Tabnine CLI through your organization's approved setup. Confirm it is available in the same terminal that will launch the backend:

```sh
tabnine --help
```

Set these values in the root `.env`:

```dotenv
AI_PROVIDER=tabnine_cli
TABNINE_CLI_PATH=tabnine
TABNINE_TIMEOUT_SECONDS=60
```

If the executable is not on that terminal's `PATH`, set `TABNINE_CLI_PATH` to its absolute path. The adapter invokes the CLI with `-p` and `--output-format json`; the installed CLI must support these options. Azure values can remain empty. An executable being found does not prove authentication or a model request will succeed.

**Option B — Azure OpenAI**

Set these values in the root `.env`, replacing the placeholders with your resource and deployment details:

```dotenv
AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=<your-secret-key>
AZURE_OPENAI_MODEL=<your-deployment-name>
```

Use a deployment that supports the application's structured JSON responses. Setting Azure credentials without changing `AI_PROVIDER` will still select Tabnine.

**Option C — Local rules (no AI credentials)**

Set `AI_PROVIDER=local_rules` in the root `.env`. Uploads then recognize explicit relationships in any supported text-bearing document format. Use one fact per sentence or pipe-separated line, for example:

```text
Billing Service calls Inventory API.
Billing Service | DEPENDS_ON | Orders Database
```

Names should be capitalized. A suffix such as `Service`, `Team`, `API`, or `Database` determines the entity type; other names become business concepts. The local rules only extract directly stated facts with supported verbs or ontology predicates. They do not infer facts from free-form prose. If no explicit relationship is found, the upload returns a helpful validation error instead of claiming the document was learned. Similar existing names are sent to **Questions for the team** for human review. Claims from uploads remain proposed and retain the exact source excerpt as evidence. Local rules support uploads only; Knowledge Assistant and AI-backed curation remain unavailable.

To try this mode without writing a document, upload `examples/local-rules-demo.md` using namespace `local-demo`, then select `local-demo` in Graph Explorer. The graph appears only after you upload the file.

**Without a working provider or local rules:** the backend can start and serve health checks and existing knowledge, but upload, assistant, and AI-backed curation endpoints return HTTP 503. If an AI provider initializes but authentication or inference later fails, the request reports a provider error instead. Restart the backend after changing provider settings.

## 3. Start Neo4j

From the repository root:

```sh
podman compose --env-file .env up -d neo4j
podman compose --env-file .env ps
podman compose --env-file .env logs --tail=50 neo4j
```

Docker alternative: replace `podman compose` with `docker compose` in this guide.

Wait until the database is ready. Open [Neo4j Browser](http://localhost:7474) and connect using `bolt://localhost:7687`, username `neo4j`, and the password from `.env`.

The service uses Neo4j **5.26.30** and named volumes for database data and logs. On an existing volume, changing `.env` does not reset the database password; use the existing password or change it through Neo4j's supported password workflow. Do not delete volumes to fix a login problem.

## 4. Install backend dependencies

macOS/Linux, starting from the repository root:

```sh
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

Windows PowerShell, starting from the repository root:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

If PowerShell blocks activation, you can use `.\.venv\Scripts\python.exe` in place of `python` without changing execution policy. Launch the server with `.\.venv\Scripts\python.exe -m uvicorn ...` in that case.

## 5. Optional: add demo knowledge

From `backend`, with the virtual environment activated and Neo4j running:

```sh
python scripts/seed_phase2.py
```

This adds the TSTVS demo team, Aggregator Service, Scheduled Dispatch concept, claims, evidence, and an open gap. It can be rerun without duplicating its fixed-ID records. On a fresh database, the expected summary is 3 entities, 2 claims, 1 source, 2 evidence records, and 1 open gap. Skip this step if you want to start without demo data.

## 6. Start the backend — terminal 1

From `backend`, with the virtual environment activated:

```sh
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Leave this terminal running. Check:

- [Health](http://localhost:8000/api/health): expect `{"status":"UP","neo4j":"UP"}` when the database is reachable.
- [API documentation](http://localhost:8000/docs): available routes and request formats.

The health response checks Neo4j, **not AI readiness**. If Neo4j was down during backend startup, start it and restart the backend so schema initialization runs.

## 7. Start the frontend — terminal 2

Open a new terminal at the repository root:

```sh
cd frontend
npm ci
npm run dev -- --host localhost --port 5173 --strictPort
```

Leave it running and open [the application](http://localhost:5173).

The UI calls its own `/api` path, and Vite forwards it to the backend. If you change the backend address, create an ignored `frontend/.env.local` file containing:

```dotenv
VITE_PROXY_TARGET=http://127.0.0.1:8001
```

Restart Vite after changing that file. If you change the UI address or port, update `FRONTEND_ORIGIN` in the root `.env` to the **exact browser origin**, then restart the backend. `http://localhost:5173` and `http://127.0.0.1:5173` are different origins; the default configuration expects you to open the `localhost` URL.

## 8. Try the team-learning workflow

1. Sign in with `APP_PASSWORD` from the ignored root `.env`. Check that Backend and Neo4j show **UP** in the UI.
2. Choose the **Active namespace**. Under **Learn from a document**, select one or more PDF, DOCX, PPTX, TXT, or Markdown files, or select a folder, then click **Upload and learn**. Selecting a folder suggests its folder name as the namespace; edit it if needed. Each file goes to the active namespace. The default per-file limit is 10 MB; documents must contain extractable text (there is no OCR step).
3. Read the learning report for new entities, recognized names, learned aliases, and unresolved terms.
4. In **Questions for the team**, choose the correct existing entity or create a separate entity, explain the decision, and apply it. The decision persists in Neo4j and applies supported relationships that were waiting for that identity.
5. In **Review uploaded claims**, use the same namespace. Select a proposed claim, read its current file evidence, then enter your name and a reason to **Confirm** or **Reject** it. The decision and reason appear under **Recorded decisions** in that section; a reviewed claim can be reopened if the decision needs correction. This is separate from resolving an entity name under **Questions for the team**.
6. Use the other **Recorded decisions** section to inspect remembered entity-identity decisions and original evidence. The graph refreshes after a claim decision, identity decision, or successful upload.
7. With Tabnine or Azure OpenAI configured, ask the **Knowledge Assistant** a question about the uploaded material using the same namespace. Inspect its supporting evidence and proposed/confirmed status; it should not invent missing knowledge. The assistant is unavailable in local rules mode.

Use the same filename and namespace when replacing a document. A successful replacement preserves history and makes the new version's evidence current. Identical uploads normally skip extraction; select **Reprocess even if unchanged** to analyze an earlier upload with the current learning policy. Existing duplicate nodes are not automatically merged.

## 9. Tests and build checks

From `backend`, with the virtual environment activated:

```sh
# Unit tests; no running Neo4j or AI credentials needed.
python -m pytest tests/unit -q
```

For integration tests and the deterministic evaluation, configure `NEO4J_*` to point to a **disposable test database**, not a team knowledge database. These commands create and clean up test records. An already-running backend should not be pointed at a database you are treating as disposable.

```sh
# From backend, with the test database running:
python -m pytest tests -q
python scripts/run_phase9_evaluation.py
```

Integration tests may skip when Neo4j is unavailable; skipped tests do not verify database behavior. These checks use deterministic AI responses, not a real-provider quality benchmark.

From `frontend`:

```sh
npm run build
```

This checks TypeScript and writes the production UI to `frontend/dist`. It does not deploy the application or start a production backend.

## 10. Stop and restart

Press **Ctrl+C** in the backend and frontend terminals. From the repository root, stop only this project's database service:

```sh
podman compose --env-file .env stop neo4j
```

Start it again with the command in step 3. Reactivate the backend virtual environment in a new terminal, then repeat steps 6 and 7; dependency installation is only needed initially or after dependencies change. Do not use volume deletion or global container-pruning commands for normal shutdown.

Local state lives in Neo4j's named volumes, `data/uploads`, and `data/langgraph_checkpoints.db` (relative to the repository root by default). Back these up together before moving or resetting the environment.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Backend fails with missing settings | Ensure the root `.env` exists and all `NEO4J_*` and `FRONTEND_ORIGIN` values are present. |
| Python dependency installation fails | Verify the active interpreter is Python 3.13 and recreate only the project's virtual environment if it was made with another version. |
| Vite reports an unsupported Node version | Compare `node --version` with the prerequisite above, then reinstall dependencies with `npm ci`. |
| Database shows DOWN | Check container runtime, Compose logs, port 7687, credentials, and whether shell environment variables override `.env`. Restart the backend after the database becomes ready. |
| AI features are unavailable | Check `AI_PROVIDER`, CLI path/authentication or all three Azure settings, and backend logs. Restart the backend after configuration changes. |
| Upload times out or returns a provider error | Check provider connectivity, authentication, schema-valid responses, and `TABNINE_TIMEOUT_SECONDS` when using Tabnine. Try a short text document first. |
| UI cannot reach the API | Check the backend health URL, `VITE_API_ROOT`, and the exact `FRONTEND_ORIGIN`. Restart the relevant server after changes. |
| Port is already in use | Stop the known conflicting project process or deliberately choose another port and update the corresponding settings. Do not stop unrelated services blindly. |
| No new facts after an unchanged upload | Enable **Reprocess even if unchanged**, and inspect saved identity questions for deferred relationships. |

See [README.md](README.md) for feature details and [the research notes](docs/team-learning-research.md) for architectural decisions and current limitations.
