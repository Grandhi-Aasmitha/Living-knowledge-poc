# Living Knowledge POC Guidelines

- This repository is currently scoped to Phase 1 infrastructure/bootstrap unless the user explicitly approves a later phase.
- Do not add knowledge-domain functionality early: no Entity, Claim, Evidence, KnowledgeGap, graph model, repositories, graph traversal, ingestion, LLM, LangGraph, LangChain, or PydanticAI functionality in Phase 1.
- Use Podman/Podman Compose with project-specific names for this repo.
- Never run destructive global Podman commands such as pruning all containers/volumes or removing unrelated containers/volumes.
- Stop or restart only the project-specific Neo4j service/container when needed: `neo4j` / `living-knowledge-neo4j`.
- Keep `.env` uncommitted and do not print real secrets or credentials.
