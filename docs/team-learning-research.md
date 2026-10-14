# Research and implementation decisions: a continuously learning team expert

Checked: 14 October 2026. This is a dated review of primary sources, not a claim that any approach is universally best. Project activity and reference implementations provide evidence of practical use; they do not establish deployment counts or comparable accuracy.

## Relevant systems and research

| Reference | What it contributes | Fit for this project |
| --- | --- | --- |
| [Graphiti / Zep](https://github.com/getzep/graphiti) | Incremental temporal graphs, source episodes, evolving entities, and hybrid retrieval | The closest architectural reference for maintaining changing organizational facts. Borrow provenance and lifecycle patterns; preserve our claim statuses, human decisions, and provider boundary. |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) and [the original paper](https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/) | Entity graphs and community summaries for broad questions across a corpus | Useful for future questions such as “How does the whole team work?” The repository currently describes itself as largely in maintenance mode. It is not the replacement selected for our learning engine. |
| [LangMem](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) | Semantic, episodic and procedural memory; updates and consolidation; active and background processing | A useful separation of memory types. Domain facts should remain in Neo4j; background work should later be a durable worker rather than an untracked request task. |
| [Mem0](https://github.com/mem0ai/mem0) | Persistent memory for agents and applications | A practical memory-layer reference. Its general agent-memory purpose does not replace our domain ontology, evidence lifecycle, or team review workflows. |
| [A-MEM](https://arxiv.org/abs/2502.12110) (2025) | Linking new observations to existing memories and evolving earlier representations | Supports the direction of comparing new observations with existing understanding. Generated summaries or interpretations should be versioned and traceable. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | Evaluation of extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention | A single-turn answer fixture is insufficient. Test the sequence of learning, correction, later recall, and changed sources. |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493) (May 2026) | Environment-specific experience, dynamic state, workflow knowledge, gotchas, and premise awareness | Especially close to “become an experienced colleague.” Future evaluation should include workflows and mistaken premises, beyond names and individual facts. |
| [Beyond Similarity / MemGate](https://arxiv.org/abs/2606.06054) (June 2026) | Treats memory admission as a trust boundary rather than simply similarity retrieval | Similarity can propose candidates; namespace, source context, ontology compatibility, and validation must govern admission. Public research must not become an assumed fact about a private team. |

## What we adopted

Separate source observations from canonical knowledge. `LearningBatch` stores the original extracted proposal and chunk context. `EntityMention` stores the interpretation, candidates, original AI reason/confidence, and eventual human decision. The canonical graph receives claims only when their referenced entities are resolved and their evidence is supported by the original source.

Persist uncertainty. Identity questions survive browser refresh and backend restart. A human can match a mention to an existing entity or establish a separate entity, with a required reason. Claims are recovered from saved proposals, not regenerated from model memory. File facts remain PROPOSED when only their identity has been confirmed; human curation keeps its existing CONFIRMED policy.

Make updates explicit. New documents start without a current version. Failed processing can retry cached proposals. Successful publication activates the new version's evidence and deactivates earlier evidence from the same document. Earlier observations and claims remain available for provenance. Replacing one source does not invalidate supporting evidence from a different document or person.

Keep names governed. Candidate ranking considers extracted aliases and searches the namespace without the previous first-200 truncation. Exact names stay fast to interpret; uncertain AI decisions become questions. AI identity decisions are recorded before alias learning, and alias reservations prevent competing canonical entities of the same type from silently taking the same name. Human decisions can be retried idempotently.

Keep identity policy shared. Both document ingestion and human gap curation use the same contextual resolver in runtime wiring. Ambiguous curation identities also become saved questions, carrying their original human answer and gap context.

## What these sources do not prove

They do not prove that a model-reported confidence of 0.9 is calibrated, that embeddings understand an organization, or that a particular library will outperform this application. Published benchmark scores use different tasks, models, and conditions. This implementation does not install those memory frameworks or reproduce their claimed performance.

The current layer still uses lexical candidate generation, document context, and typed AI adjudication. It does not add embeddings, corpus community summaries, autonomous ontology edits, an external research monitor, or model fine-tuning.

## Next research-backed milestones

1. Build a team-specific identity evaluation corpus: acronyms, renamed systems, identical names across teams, team/application distinctions, negative matches, and ambiguous mentions. Measure candidate recall and false-merge rate separately.
2. Add versioned source authority and freshness rules. Document replacement is now handled, but truth-validity time, collection time, and verification time are different concepts.
3. Add structured workflows, decisions and rationale, with allowed derivations and qualified relationships. This is the richer semantic layer needed for impact questions.
4. Evaluate bounded hybrid candidate retrieval against the lexical baseline before selecting an embedding provider. Keep namespace and identity decisions deterministic where possible.
5. Add durable background ingestion/consolidation and a source-change notification queue, with retries, rate limits, and auditable publication.
6. Add reversible duplicate reconciliation with explicit human selection and an audit trail. Current alias conflicts stay visible rather than silently merging historical nodes.
7. Test longitudinal expertise: introduce a system, teach an alias, resolve ambiguity, change ownership, remove a source fact, ask an outdated-premise question, and verify evidence-backed answers and refusal.

## Validation in this repository

`backend/tests/integration/test_team_learning.py` exercises learning across uploads and service restarts using Neo4j and deterministic AI responses. Existing unit and integration suites cover provider boundaries, curation, provenance, gaps, conflicts, and assistant citation handling. These checks validate application behavior; real-provider extraction and resolution quality still require the identity corpus above.

For this implementation check, all 175 backend tests passed against an isolated Neo4j 5.26 instance, the deterministic golden evaluation passed 10/10 cases, and the frontend production build passed. A synthetic browser test confirmed an identity decision, recovered a waiting relationship, and answered through its learned alias with a document citation. The temporary test runtime used Python 3.12; the repository targets Python 3.13, which still needs a matching-environment check. No real team database or AI-provider quality benchmark was used for these results.
