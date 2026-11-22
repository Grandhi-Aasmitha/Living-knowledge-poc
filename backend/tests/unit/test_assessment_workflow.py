import asyncio
from langgraph.checkpoint.memory import MemorySaver

from app.assessment.models import StepFinding, STAGES
from app.assessment.workflow import AssessmentWorkflow
from app.assistant.models import EntityResolution, MatchedEntity, RetrievedClaim, RetrievedEvidence
from app.domain.enums import ClaimStatus


class FakeRepository:
    async def list_application_capabilities(self, namespace):
        return []

    async def resolve_entities(self, names, namespace):
        return [EntityResolution(requested_name=name, matches=[MatchedEntity(
            id="source-id", label=name, entity_type="SYSTEM", namespace=namespace,
        )]) for name in names]

    async def get_claim_context(self, entity_ids, predicates, direction, namespace, max_claims, max_evidence_per_claim):
        return [RetrievedClaim(
            claim_id="claim-1", subject_entity_id="source-id", subject_name="Source App",
            subject_type="SYSTEM", predicate="DEPENDS_ON", object_entity_id=None,
            object_name=None, object_type=None, object_value="Shared Database",
            claim_status=ClaimStatus.CONFIRMED, confidence=0.9,
            evidence=[RetrievedEvidence(
                evidence_id="evidence-1", source_id="source-1", source_type="FILE_UPLOAD",
                source_title="architecture.md", excerpt="Source App depends on Shared Database.",
            )],
        )]

    async def get_open_gaps(self, entity_ids):
        return []

    async def get_open_conflicts(self, claim_ids):
        return []


class FakeAI:
    async def generate_structured(self, prompt, response_model):
        import json
        context = json.loads(prompt)
        if context["stage"] == STAGES[0] and not context["clarifications"]:
            return StepFinding(summary="Dependency found; operating details missing.", completeness="PARTIAL",
                               claim_ids=["claim-1"], evidence_ids=["evidence-1"],
                               missing_question="Who operates the source app?")
        return StepFinding(summary=f"{context['stage']}: assessment based on the supplied dependency and clarifications.",
                           completeness="PARTIAL", claim_ids=["claim-1"], evidence_ids=["evidence-1"])


def test_assessment_pauses_resumes_reviews_and_restores_checkpoint():
    async def scenario():
        checkpointer = MemorySaver()
        workflow = AssessmentWorkflow(FakeRepository(), FakeAI(), checkpointer)
        first = await workflow.start("a1", "team", "Source App", None)
        assert first.status == "WAITING_FOR_INPUT"
        assert first.current_stage == "SECURITY_AND_NFR"
        assert first.target_discovery_status == "NO_SUITABLE_TARGET"
        assert first.findings[1].stage == "TARGET_DISCOVERY"
        restored = AssessmentWorkflow(FakeRepository(), FakeAI(), checkpointer)
        assert (await restored.get("a1")).status == "WAITING_FOR_INPUT"
        draft = await restored.answer("a1", "Security requirements are not documented")
        assert draft.status == "WAITING_FOR_REVIEW"
        assert len(draft.findings) == len(STAGES)
        assert draft.clarifications[0]["answer"] == "Security requirements are not documented"
        assert draft.findings[-1].outcome == "NEEDS_REVIEW"
        approved = await restored.review("a1", "APPROVE", "Architect", "Evidence checked")
        assert approved.status == "APPROVED"
        assert approved.review_history[0]["reviewer"] == "Architect"

    asyncio.run(scenario())


def test_revision_restarts_assessment_and_preserves_review_history():
    async def scenario():
        workflow = AssessmentWorkflow(FakeRepository(), FakeAI(), MemorySaver())
        await workflow.start("a2", "team", "Source App", None)
        draft = await workflow.answer("a2", "Security requirements are not documented")
        assert draft.status == "WAITING_FOR_REVIEW"
        revised = await workflow.review("a2", "REVISE", "Architect", "Check the retirement option")
        assert revised.status == "WAITING_FOR_REVIEW"
        assert len(revised.findings) == len(STAGES)
        assert revised.review_history[-1]["comment"] == "Check the retirement option"
        assert (await workflow.get("a2")).review_history[-1]["decision"] == "REVISE"

    asyncio.run(scenario())


def test_optional_repository_question_does_not_pause_source_analysis():
    async def scenario():
        workflow = AssessmentWorkflow(FakeRepository(), FakeAI(), MemorySaver())
        result = await workflow.start("a3", "team", "Source App", None)
        assert result.current_stage == "SECURITY_AND_NFR"
        assert result.findings[0].stage == "SOURCE_AND_DEPENDENCIES"
        assert "repository" not in (result.question or "").lower()

    asyncio.run(scenario())
