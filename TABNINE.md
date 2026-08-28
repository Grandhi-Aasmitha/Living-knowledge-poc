# Living Knowledge POC Guidelines

- This repository is currently implemented through Phase 3 when explicitly requested; do not proceed to later phases without explicit user approval.
- Phase 3 scope is a single human-in-the-loop curation workflow for `MISSING_CONSUMER` knowledge gaps using PydanticAI for question/answer LLM interactions and LangGraph for interrupt/resume/checkpoint orchestration.
- Do not add Phase 4+ functionality: no document ingestion, graph visualization, Cytoscape, semantic search, embeddings, automatic gap detection, conflict detection, knowledge assistant, authentication, queues, Redis, Celery, Kubernetes, LangChain, Pydantic Graph, or generic workflow frameworks.
- Neo4j stores durable knowledge only: Entity, Claim, Evidence, KnowledgeSource, and KnowledgeGap. Do not store LangGraph checkpoint/runtime state in Neo4j.
- Use Podman/Podman Compose with project-specific names for this repo.
- Never run destructive global Podman commands such as pruning all containers/volumes or removing unrelated containers/volumes.
- Stop or restart only the project-specific Neo4j service/container when needed: `neo4j` / `living-knowledge-neo4j`.
- Keep `.env` uncommitted and do not print real secrets or credentials. Runtime SQLite checkpoint files under `data/*.db` are local artifacts and must not be committed.
