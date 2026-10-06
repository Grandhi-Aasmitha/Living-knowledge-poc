# Living Knowledge POC Guidelines

Current project phase: Phase 9 — Knowledge Assistant + Evaluation.

Implemented phases:
- Phase 1 — Project bootstrap and Neo4j connectivity
- Phase 2 — Canonical knowledge core
- Phase 3 — Human-in-the-loop curation
- Phase 3.1 — Pluggable AI provider with Tabnine CLI
- Phase 4 — Document ingestion and structured knowledge extraction
- Phase 5 — Graph Explorer
- Phase 6 — Automatic knowledge gap detection
- Phase 8 — Conflict detection and human resolution

Deferred:
- Phase 7 — Confluence MCP integration is deferred because Atlassian MCP authentication is not currently available.

Phase 9 implementation is explicitly allowed.

Phase 9 scope:
- read-only Knowledge Assistant
- typed bounded query planning
- deterministic Neo4j retrieval
- evidence-backed answer generation
- citation validation
- open-gap awareness
- open-conflict awareness
- React Knowledge Assistant UI
- deterministic golden evaluation

Phase 9 must NOT include:
- arbitrary Cypher
- AI-generated Cypher
- assistant database writes
- LangGraph assistant workflows
- conversation memory
- chat history persistence
- embeddings
- vector search
- semantic search
- LLM-as-judge evaluation
- Confluence implementation
- MCP integration
- Phase 7 work
- functionality beyond Phase 9

Architectural rules:
- Neo4j = canonical knowledge
- StructuredAIClient = AI provider boundary
- Tabnine CLI = default current POC AI provider
- PydanticAI/Azure OpenAI = optional StructuredAIClient adapter for local POC runtime when explicitly configured
- LangGraph = HITL curation only
- Knowledge Assistant = read-only
- LLM never gets direct Neo4j access
- LLM never generates or executes Cypher

- Neo4j stores durable knowledge only: Entity, Claim, Evidence, KnowledgeSource, KnowledgeGap, SourceDocument, SourceVersion, SourceChunk, and KnowledgeConflict. Do not store LangGraph checkpoint/runtime state in Neo4j.
- Use Podman/Podman Compose with project-specific names for this repo.
- Never run destructive global Podman commands such as pruning all containers/volumes or removing unrelated containers/volumes.
- Stop or restart only the project-specific Neo4j service/container when needed: `neo4j` / `living-knowledge-neo4j`.
- Keep `.env` uncommitted and do not print real secrets or credentials. Runtime SQLite checkpoint files under `data/*.db` are local artifacts and must not be committed.
