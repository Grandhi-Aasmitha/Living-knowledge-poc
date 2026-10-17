# Living Knowledge POC Guidelines

Current project phase: Team Learning — user-authorized extension beyond Phase 9.

User-authorized learning scope:
- durable LearningBatch, EntityMention, and AliasBinding records in Neo4j
- saved identity clarification questions and human decisions
- replay of deferred source-backed claims
- one contextual identity policy across ingestion and human curation
- safe same-document retries and team-scoped document identity
- source-version evidence activity and historical provenance
- research-informed design and longitudinal learning evaluation

The assistant remains read-only. External research is maintained as a dated design document and is not admitted as a fact about a private team. Embeddings, arbitrary Cypher, autonomous ontology changes, and Confluence remain outside the implemented scope.

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
- unrequested functionality outside the user-authorized team-learning extension

Architectural rules:
- Neo4j = canonical knowledge
- StructuredAIClient = AI provider boundary
- Tabnine CLI = default current POC AI provider
- PydanticAI/Azure OpenAI = optional StructuredAIClient adapter for local POC runtime when explicitly configured
- PydanticAI/OpenAI API = optional StructuredAIClient adapter for document extraction, curation, and the Knowledge Assistant when explicitly configured
- Local rules = optional offline StructuredAIClient adapter for explicit document relationships only; it does not serve curation or the Knowledge Assistant
- LangGraph = HITL curation only
- Knowledge Assistant = read-only
- LLM never gets direct Neo4j access
- LLM never generates or executes Cypher

- Neo4j stores durable knowledge only: Entity, Claim, Evidence, KnowledgeSource, KnowledgeGap, SourceDocument, SourceVersion, SourceChunk, KnowledgeConflict, LearningBatch, EntityMention, and AliasBinding. Do not store LangGraph checkpoint/runtime state in Neo4j.
- Use Podman/Podman Compose with project-specific names for this repo.
- Never run destructive global Podman commands such as pruning all containers/volumes or removing unrelated containers/volumes.
- Stop or restart only the project-specific Neo4j service/container when needed: `neo4j` / `living-knowledge-neo4j`.
- Keep `.env` uncommitted and do not print real secrets or credentials. Runtime SQLite checkpoint files under `data/*.db` are local artifacts and must not be committed.
