import asyncio
from typing import Any

from pydantic import BaseModel

from app.assistant.models import KnowledgeQueryPlan, QueryDirection
from app.assistant.query_planner import QueryPlanner


class FakeClient:
    def __init__(self, response: KnowledgeQueryPlan) -> None:
        self.response = response
        self.prompt = ""
        self.response_model: type[BaseModel] | None = None

    async def generate_structured(self, prompt: str, response_model: type[BaseModel]) -> Any:
        self.prompt = prompt
        self.response_model = response_model
        return self.response


def run(coro):
    return asyncio.run(coro)


def test_plans_owner_question() -> None:
    client = FakeClient(KnowledgeQueryPlan(entity_names=["Scheduler Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING))

    plan = run(QueryPlanner(client).plan("Who owns Scheduler Service?"))

    assert plan.entity_names == ["Scheduler Service"]
    assert plan.predicates == ["OWNS"]
    assert plan.direction == QueryDirection.INCOMING
    assert "allowed_predicates" in client.prompt
    assert "Cypher" in client.prompt


def test_plans_producer_question() -> None:
    client = FakeClient(KnowledgeQueryPlan(entity_names=["Aggregator Service"], predicates=["PRODUCES", "PUBLISHES_TO"], direction=QueryDirection.OUTGOING))

    plan = run(QueryPlanner(client).plan("What does Aggregator Service produce?"))

    assert plan.entity_names == ["Aggregator Service"]
    assert set(plan.predicates) == {"PRODUCES", "PUBLISHES_TO"}
    assert plan.direction == QueryDirection.OUTGOING


def test_plans_consumer_question() -> None:
    client = FakeClient(KnowledgeQueryPlan(entity_names=["Scheduled Dispatch"], predicates=["CONSUMES"], direction=QueryDirection.INCOMING))

    plan = run(QueryPlanner(client).plan("What consumes Scheduled Dispatch?"))

    assert plan.entity_names == ["Scheduled Dispatch"]
    assert plan.predicates == ["CONSUMES"]
    assert plan.direction == QueryDirection.INCOMING


def test_plans_broad_summary_question() -> None:
    client = FakeClient(KnowledgeQueryPlan(entity_names=["Aggregator Service"], predicates=[], direction=QueryDirection.BOTH))

    plan = run(QueryPlanner(client).plan("Tell me about Aggregator Service."))

    assert plan.entity_names == ["Aggregator Service"]
    assert plan.predicates == []
    assert plan.direction == QueryDirection.BOTH
