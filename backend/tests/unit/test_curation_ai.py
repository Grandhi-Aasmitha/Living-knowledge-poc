import asyncio
import json

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.answer_interpreter import AnswerInterpreter
from app.ai.models import AnswerInterpretation, QuestionDraft
from app.ai.question_generator import QuestionGenerator
from app.domain.entity import Entity
from app.domain.enums import GapPriority
from app.domain.gap import KnowledgeGap


def run(coro):
    return asyncio.run(coro)


def function_model(payload: dict) -> FunctionModel:
    def respond(messages, info: AgentInfo):
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(respond)


def sample_gap() -> KnowledgeGap:
    return KnowledgeGap(
        id="test:gap:missing-consumer",
        entity_id="test:concept:scheduled-dispatch",
        gap_type="MISSING_CONSUMER",
        description="The consumer of Scheduled Dispatch is currently unknown.",
        priority=GapPriority.HIGH,
    )


def sample_entity() -> Entity:
    return Entity(
        id="test:concept:scheduled-dispatch",
        entity_type="BUSINESS_CONCEPT",
        canonical_name="Scheduled Dispatch",
        namespace="test",
    )


def test_question_generator_returns_question_draft() -> None:
    model = function_model({"question": "Which service currently consumes Scheduled Dispatch?"})
    generator = QuestionGenerator(model)

    with override_allow_model_requests(False):
        draft = run(generator.generate(sample_gap(), sample_entity(), []))

    assert isinstance(draft, QuestionDraft)
    assert draft.question.endswith("?")


def test_answer_interpreter_resolves_scheduler_service() -> None:
    model = function_model(
        {
            "can_resolve": True,
            "entity_name": "Scheduler Service",
            "entity_type": "SERVICE",
            "reason": None,
        }
    )
    interpreter = AnswerInterpreter(model)

    with override_allow_model_requests(False):
        interpretation = run(
            interpreter.interpret(
                question="Which service consumes Scheduled Dispatch?",
                answer="Scheduler Service",
                gap=sample_gap(),
                entity=sample_entity(),
            )
        )

    assert interpretation == AnswerInterpretation(
        can_resolve=True,
        entity_name="Scheduler Service",
        entity_type="SERVICE",
        reason=None,
    )


def test_answer_interpreter_handles_unknown_answer() -> None:
    model = function_model(
        {
            "can_resolve": False,
            "entity_name": None,
            "entity_type": None,
            "reason": "The answer does not identify a consumer.",
        }
    )
    interpreter = AnswerInterpreter(model)

    with override_allow_model_requests(False):
        interpretation = run(
            interpreter.interpret(
                question="Which service consumes Scheduled Dispatch?",
                answer="I don't know",
                gap=sample_gap(),
                entity=sample_entity(),
            )
        )

    assert interpretation.can_resolve is False
    assert interpretation.entity_name is None
    assert interpretation.entity_type is None


def test_answer_interpreter_invalid_structured_data_fails_validation() -> None:
    model = function_model({"can_resolve": True, "entity_name": "", "entity_type": None})
    interpreter = AnswerInterpreter(model)

    with override_allow_model_requests(False), pytest.raises(UnexpectedModelBehavior):
        run(
            interpreter.interpret(
                question="Which service consumes Scheduled Dispatch?",
                answer="Scheduler Service",
                gap=sample_gap(),
                entity=sample_entity(),
            )
        )
