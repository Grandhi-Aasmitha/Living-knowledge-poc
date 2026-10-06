# Structured AI Provider Adapter Implementation Guide

This guide captures the provider-switching pattern used in the Living Knowledge POC so the same approach can be replicated in another repository.

## Goal

Build all AI-dependent application features against one provider-neutral interface:

```text
Application feature
  -> StructuredAIClient
  -> selected provider implementation
     - Tabnine CLI by default
     - Azure OpenAI / PydanticAI when explicitly configured
```

The application should not import or depend on `TabnineCliClient`, Azure OpenAI, or PydanticAI directly. It should only request typed Pydantic output from `StructuredAIClient`.

## Key Design Rules

1. **One provider-neutral interface**
   - All AI consumers call `generate_structured(prompt, response_model)`.
   - `response_model` is a Pydantic model.
   - The returned value is already validated as that Pydantic model.

2. **Provider choice is explicit**
   - Select provider using `AI_PROVIDER`.
   - Supported values in this POC:
     - `tabnine_cli`
     - `azure_openai`
   - Do not automatically fallback from one provider to another.

3. **Application code remains provider-agnostic**
   - Features such as curation, extraction, query planning, and answer generation receive `StructuredAIClient`.
   - They must not know whether Tabnine CLI or Azure OpenAI is active.

4. **Structured output is mandatory**
   - Providers must return JSON that validates against the requested Pydantic model.
   - Invalid structured output raises `AIProviderError`.

5. **No secrets or prompt/model output logging**
   - Do not log prompts, document contents, engineer answers, raw provider output, stderr, API keys, or credentials.
   - If logging failures, log only safe categories and validation locations/types.

## Files to Add

Recommended structure:

```text
backend/app/ai/
  client.py
  provider.py
  tabnine_cli_client.py
  pydantic_ai_client.py
  model.py              # if using Azure/PydanticAI model construction
```

Optional consumers can live elsewhere, for example:

```text
backend/app/ai/question_generator.py
backend/app/ai/answer_interpreter.py
backend/app/ai/knowledge_extractor.py
backend/app/assistant/query_planner.py
backend/app/assistant/answer_generator.py
```

## Configuration

Add settings similar to:

```python
class Settings(BaseSettings):
    ai_provider: str = "tabnine_cli"
    tabnine_cli_path: str = "tabnine"
    tabnine_timeout_seconds: int = 60

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_model: str | None = None

    @field_validator("ai_provider")
    @classmethod
    def ai_provider_must_be_supported(cls, value: str) -> str:
        if value not in {"tabnine_cli", "azure_openai"}:
            raise ValueError("ai_provider must be tabnine_cli or azure_openai")
        return value

    @field_validator("tabnine_timeout_seconds")
    @classmethod
    def timeout_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeout must be positive")
        return value
```

`.env.example` should contain non-secret placeholders only:

```env
AI_PROVIDER=tabnine_cli
TABNINE_CLI_PATH=tabnine
TABNINE_TIMEOUT_SECONDS=60
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_MODEL=
```

Never commit real `.env` values.

## Provider-Neutral Interface

Create `client.py`:

```python
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredAIClient(Protocol):
    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        pass


class AIProviderError(RuntimeError):
    pass
```

All provider implementations must satisfy this protocol.

## Provider Factory

Create `provider.py`:

```python
from pathlib import Path
from shutil import which

from app.ai.client import AIProviderError, StructuredAIClient
from app.ai.model import build_ai_model
from app.ai.pydantic_ai_client import PydanticAIClient
from app.ai.tabnine_cli_client import TabnineCliClient
from app.config import Settings


def build_structured_ai_client(settings: Settings) -> StructuredAIClient:
    if settings.ai_provider == "tabnine_cli":
        resolved_cli_path = _resolve_executable(settings.tabnine_cli_path)
        if resolved_cli_path is None:
            raise AIProviderError("Tabnine CLI executable is not available")
        return TabnineCliClient(
            cli_path=resolved_cli_path,
            timeout_seconds=settings.tabnine_timeout_seconds,
        )

    if settings.ai_provider == "azure_openai":
        model = build_ai_model(settings)
        if model is None:
            raise AIProviderError("Azure OpenAI configuration is incomplete")
        return PydanticAIClient(model)

    raise AIProviderError("Unknown AI provider")


def _resolve_executable(cli_path: str) -> str | None:
    path = Path(cli_path)
    if path.is_absolute():
        return str(path) if path.is_file() else None
    return which(cli_path)
```

## Tabnine CLI Client

### Responsibilities

`TabnineCliClient` should:

- Run Tabnine CLI asynchronously.
- Avoid `shell=True`.
- Avoid building shell command strings.
- Pass the prompt as a process argument.
- Request JSON output using Tabnine CLI options.
- Add the Pydantic JSON schema to the prompt.
- Parse observed Tabnine JSON envelopes.
- Validate against the supplied Pydantic model.
- Enforce timeout and output-size limits.
- Raise `AIProviderError` for all provider failures.

### Command Shape

The expected command shape is:

```text
tabnine -p <prompt> --output-format json
```

On Windows, `tabnine` may resolve to a `.cmd` shim. Python `asyncio.create_subprocess_exec` cannot execute `.cmd` shims directly without a shell. To keep `shell=False`, resolve the shim internally to:

```text
node <tabnine.mjs> -p <prompt> --output-format json
```

The POC locates the active Tabnine bundle through:

```text
%USERPROFILE%/.tabnine/agent/.bundles/.active
%USERPROFILE%/.tabnine/agent/.bundles/<version>/tabnine.mjs
```

### Prompt Wrapping

Append an instruction and schema to every provider prompt:

```python
def _build_prompt(prompt: str, response_model: type[BaseModel]) -> str:
    schema = json.dumps(response_model.model_json_schema(), sort_keys=True)
    separator = chr(10) + chr(10)
    return separator.join(
        [
            prompt,
            "Return only a JSON object that validates against the schema below. "
            "Do not wrap it in another object. Do not include markdown, explanation, prose, or additional fields.",
            schema,
        ]
    )
```

### Output Envelopes

The POC observed these Tabnine output shapes:

```json
{"answer":"{...model json...}"}
```

and:

```json
{
  "session_id": "...",
  "response": "{...model json...}",
  "stats": {}
}
```

The parser should support only known envelope fields such as:

- `response`
- `answer`

It should not do arbitrary regex guessing or JSON repair.

### Safe Failure Handling

Recommended errors:

```text
Tabnine CLI provider could not be started
Tabnine CLI provider timed out
Tabnine CLI provider output exceeded safety limit
Tabnine CLI provider exited with an error
Tabnine CLI provider returned no output
Tabnine CLI provider did not return a JSON response
Tabnine CLI provider returned malformed JSON
Tabnine CLI provider returned schema-invalid JSON (<safe validation summary>)
```

A safe validation summary may include Pydantic error locations and types only:

```text
claims.0.predicate:value_error
entities.2.entity_type:value_error
claims.1.object_entity:string_type
root:value_error
```

Do not include raw model output, input values, document content, prompt text, or stderr.

## PydanticAI / Azure Client

Create `pydantic_ai_client.py`:

```python
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent

from app.ai.client import AIProviderError

T = TypeVar("T", bound=BaseModel)


class PydanticAIClient:
    def __init__(self, model: Any) -> None:
        self._model = model

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        try:
            agent = Agent(self._model, output_type=response_model)
            result = await agent.run(prompt)
            return result.output
        except Exception as error:
            raise AIProviderError("PydanticAI provider failed to generate structured output") from error
```

Keep Azure model construction isolated in `model.py`. Return `None` or raise provider-unavailable when Azure configuration is incomplete. Do not make missing Azure config block `tabnine_cli` usage.

## Application Integration Pattern

In application startup:

```python
try:
    ai_client = build_structured_ai_client(settings)
except AIProviderError as error:
    app.state.ai_unavailable_reason = str(error)
    ai_client = None
```

For AI-dependent services:

```python
if ai_client is not None:
    app.state.question_generator = QuestionGenerator(ai_client)
    app.state.answer_interpreter = AnswerInterpreter(ai_client)
    app.state.knowledge_extractor = KnowledgeExtractor(ai_client)
    app.state.knowledge_assistant_service = KnowledgeAssistantService(
        query_planner=QueryPlanner(ai_client),
        repository=KnowledgeQueryRepository(neo4j),
        answer_generator=AnswerGenerator(ai_client),
    )
```

For endpoints:

- If provider is unavailable at request start: return HTTP `503`.
- If provider fails during execution: return HTTP `502`.
- Never return stderr, prompt text, raw provider output, stack traces, or secrets.

## Consumer Example

A provider-agnostic AI consumer should look like:

```python
class QueryPlanner:
    def __init__(self, ai_client: StructuredAIClient) -> None:
        self._ai_client = ai_client

    async def plan(self, question: str) -> KnowledgeQueryPlan:
        prompt = self._build_prompt(question)
        return await self._ai_client.generate_structured(prompt, KnowledgeQueryPlan)
```

The consumer imports only:

```python
from app.ai.client import StructuredAIClient
```

It must not import:

```python
TabnineCliClient
PydanticAIClient
AzureOpenAIModel
```

## Structured Models

Every AI operation should have a dedicated Pydantic response model, for example:

```python
class QuestionDraft(BaseModel):
    question: str


class ExtractedKnowledge(BaseModel):
    entities: list[ExtractedEntity]
    claims: list[ExtractedClaim]
    unresolved_terms: list[str] = []
```

Use validators to enforce application rules:

- allowed entity types
- allowed predicates
- required IDs/names
- confidence range
- exactly one of object entity or literal value
- all claim references point to declared extracted entities

Do not trust provider output until Pydantic validation succeeds.

## Prompt Rules

Each prompt should include:

- task-specific instructions
- allowed vocabulary where applicable
- explicit instruction to use only supplied context/data
- prompt-injection boundary: user/document/evidence text is data, not instructions
- no markdown/prose outside JSON
- no invented facts
- no direct database/Cypher/tool access

The adapter adds the JSON schema automatically, so feature prompts do not need to duplicate the full schema manually.

## Security and Privacy Rules

Do not log:

- secrets
- API keys
- `.env` contents
- prompts
- uploaded document content
- chunks
- engineer answers
- raw Tabnine output
- provider stderr
- stack traces in API responses

Safe to log:

- provider failure category
- timeout/non-zero-exit/schema-invalid/malformed-json
- safe Pydantic validation locations/types
- document IDs/hashes prefixes if needed
- chunk sequence/count
- request status code

## Testing Strategy

### Provider Factory Tests

Verify:

- `AI_PROVIDER=tabnine_cli` builds `TabnineCliClient`.
- `AI_PROVIDER=azure_openai` builds `PydanticAIClient` when Azure config exists.
- invalid provider is rejected by settings.
- incomplete Azure config raises provider-unavailable.
- missing Tabnine executable raises provider-unavailable.
- incomplete Azure config does not block Tabnine provider.

### Tabnine Client Tests

Use a fake subprocess object. Do not call real Tabnine in normal tests.

Test:

- successful `response` envelope parsing
- successful `answer` envelope parsing
- diagnostic lines before JSON envelope
- malformed model JSON raises `AIProviderError`
- schema-invalid JSON raises `AIProviderError` with safe validation summary
- non-zero exit raises
- timeout kills process and raises
- output over safety limit raises
- command is shell-free (`shell` not passed)

### Consumer Tests

Use fake `StructuredAIClient` implementations.

Test that each consumer:

- sends appropriate task context
- requests the correct response model
- returns typed output
- propagates `AIProviderError` safely

### Endpoint Tests

Verify:

- provider unavailable maps to `503`
- provider execution failure maps to `502`
- API responses do not expose raw provider details

## Operational Checks

Quick local adapter connectivity check:

```python
import asyncio
from pydantic import BaseModel
from app.config import get_settings
from app.ai.provider import build_structured_ai_client

class ConnectivityResponse(BaseModel):
    status: str

async def main():
    client = build_structured_ai_client(get_settings())
    result = await client.generate_structured(
        "Return only JSON matching the schema with status set to ok.",
        ConnectivityResponse,
    )
    print(result.status)

asyncio.run(main())
```

Expected:

```text
ok
```

Do not print prompts, credentials, or raw provider output during checks.

## Migration Checklist for Another Repository

1. Add `StructuredAIClient` protocol and `AIProviderError`.
2. Add provider settings and `.env.example` placeholders.
3. Add `TabnineCliClient` with shell-free subprocess execution.
4. Add PydanticAI/Azure client wrapper if Azure is a future target.
5. Add provider factory `build_structured_ai_client(settings)`.
6. Update startup to build exactly one selected provider.
7. Inject `StructuredAIClient` into AI consumers.
8. Refactor consumers to call `generate_structured(prompt, ResponseModel)` only.
9. Ensure all AI outputs have strict Pydantic response models.
10. Map provider unavailable to `503` and provider execution failures to `502`.
11. Add provider/factory/client tests with fake subprocesses/fake AI clients.
12. Add safe operational logging only.
13. Verify no feature imports provider-specific client classes.
14. Verify switching `AI_PROVIDER` changes provider without application redesign.

## Common Pitfalls

- Calling Tabnine through `shell=True` or shell command strings.
- Letting feature code import `TabnineCliClient` directly.
- Falling back automatically between providers.
- Logging raw provider output to debug schema failures.
- Accepting unvalidated JSON from the provider.
- Letting the provider choose predicates, database queries, or persistence actions.
- Sending entire databases/documents when bounded context is sufficient.
- Treating schema-invalid output as partially trustworthy.

## Recommended Provider Boundary Principle

The AI provider should only produce typed structured data.

The application must remain responsible for:

- validation
- ontology/control vocabulary enforcement
- deterministic IDs
- database reads/writes
- provenance
- security decisions
- retry/idempotency semantics
- HTTP error mapping
