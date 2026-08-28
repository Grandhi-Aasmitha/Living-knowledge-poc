import asyncio
import json

import pytest

from app.ai.client import AIProviderError
from app.ai.models import AnswerInterpretation, QuestionDraft
from app.ai.tabnine_cli_client import TabnineCliClient


def run(coro):
    return asyncio.run(coro)


class FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0, delay: float = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.delay = delay
        self.killed = False

    async def communicate(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


def tabnine_stdout(model_payload: dict) -> bytes:
    envelope = {"response": json.dumps(model_payload)}
    text = "Warning: diagnostic" + chr(10) + json.dumps(envelope, indent=2) + chr(10)
    return text.encode()


def legacy_tabnine_stdout(model_payload: dict) -> bytes:
    envelope = {"answer": json.dumps(model_payload)}
    text = json.dumps(envelope) + chr(10)
    return text.encode()


async def call_with_process(monkeypatch, process: FakeProcess, response_model):
    async def fake_create_subprocess_exec(*args, **kwargs):
        assert "shell" not in kwargs
        assert "-p" in args
        output_format_index = args.index("--output-format")
        assert args[output_format_index + 1] == "json"
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    client = TabnineCliClient(timeout_seconds=0.01 if process.delay else 60)
    return await client.generate_structured("safe synthetic prompt", response_model)


def test_successful_question_draft_parsing(monkeypatch) -> None:
    process = FakeProcess(tabnine_stdout({"question": "Which service currently consumes Scheduled Dispatch?"}))

    result = run(call_with_process(monkeypatch, process, QuestionDraft))

    assert result.question == "Which service currently consumes Scheduled Dispatch?"


def test_successful_answer_interpretation_parsing(monkeypatch) -> None:
    process = FakeProcess(
        tabnine_stdout(
            {
                "can_resolve": True,
                "entity_name": "Scheduler Service",
                "entity_type": "SERVICE",
                "reason": None,
            }
        )
    )

    result = run(call_with_process(monkeypatch, process, AnswerInterpretation))

    assert result.can_resolve is True
    assert result.entity_name == "Scheduler Service"
    assert result.entity_type == "SERVICE"


def test_legacy_answer_envelope_parsing(monkeypatch) -> None:
    process = FakeProcess(legacy_tabnine_stdout({"question": "Which service currently consumes Scheduled Dispatch?"}))

    result = run(call_with_process(monkeypatch, process, QuestionDraft))

    assert result.question == "Which service currently consumes Scheduled Dispatch?"


def test_malformed_model_json_raises(monkeypatch) -> None:
    process = FakeProcess((json.dumps({"answer": "not-json"}) + chr(10)).encode())

    with pytest.raises(AIProviderError):
        run(call_with_process(monkeypatch, process, QuestionDraft))


def test_schema_invalid_result_raises(monkeypatch) -> None:
    process = FakeProcess(
        tabnine_stdout(
            {
                "can_resolve": True,
                "entity_name": "Scheduler Service",
                "entity_type": "NOT_ALLOWED",
            }
        )
    )

    with pytest.raises(AIProviderError):
        run(call_with_process(monkeypatch, process, AnswerInterpretation))


def test_non_zero_exit_raises(monkeypatch) -> None:
    process = FakeProcess(b"", b"failure", returncode=1)

    with pytest.raises(AIProviderError):
        run(call_with_process(monkeypatch, process, QuestionDraft))


def test_timeout_terminates_process_and_raises(monkeypatch) -> None:
    process = FakeProcess(b"", delay=1)

    with pytest.raises(AIProviderError):
        run(call_with_process(monkeypatch, process, QuestionDraft))

    assert process.killed is True


def test_output_over_safety_limit_raises(monkeypatch) -> None:
    process = FakeProcess(b"x" * (257 * 1024))

    with pytest.raises(AIProviderError):
        run(call_with_process(monkeypatch, process, QuestionDraft))
