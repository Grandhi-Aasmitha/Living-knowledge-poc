import asyncio
import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.client import AIProviderError


T = TypeVar("T", bound=BaseModel)


class TabnineCliClient:
    _MAX_OUTPUT_BYTES = 256 * 1024

    def __init__(self, cli_path: str = "tabnine", timeout_seconds: int = 60) -> None:
        self._cli_path = cli_path
        self._timeout_seconds = timeout_seconds

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        final_prompt = self._build_prompt(prompt, response_model)
        command = self._command_prefix()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                "-p",
                final_prompt,
                "--output-format",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise AIProviderError("Tabnine CLI provider could not be started") from error

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except TimeoutError as error:
            process.kill()
            await process.communicate()
            raise AIProviderError("Tabnine CLI provider timed out") from error

        if len(stdout) > self._MAX_OUTPUT_BYTES or len(stderr) > self._MAX_OUTPUT_BYTES:
            raise AIProviderError("Tabnine CLI provider output exceeded safety limit")

        if process.returncode != 0:
            raise AIProviderError("Tabnine CLI provider exited with an error")

        content = self._extract_content(stdout)
        try:
            return response_model.model_validate_json(content)
        except ValidationError as error:
            raise AIProviderError("Tabnine CLI provider returned schema-invalid JSON") from error
        except ValueError as error:
            raise AIProviderError("Tabnine CLI provider returned malformed JSON") from error

    def _command_prefix(self) -> list[str]:
        cli_path = Path(self._cli_path)
        if cli_path.suffix.casefold() != ".cmd":
            return [self._cli_path]

        user_profile = Path(os.environ.get("USERPROFILE", ""))
        active_file = user_profile / ".tabnine" / "agent" / ".bundles" / ".active"
        if not active_file.is_file():
            raise AIProviderError("Tabnine CLI bundle marker is unavailable")

        version = active_file.read_text(encoding="utf-8").strip()
        script = user_profile / ".tabnine" / "agent" / ".bundles" / version / "tabnine.mjs"
        if not script.is_file():
            raise AIProviderError("Tabnine CLI bundle entrypoint is unavailable")

        return [os.environ.get("NODE", "node"), str(script)]

    def _build_prompt(self, prompt: str, response_model: type[BaseModel]) -> str:
        schema = json.dumps(response_model.model_json_schema(), sort_keys=True)
        separator = chr(10) + chr(10)
        return separator.join(
            [
                prompt,
                "Return only a JSON object that validates against the schema below. Do not wrap it in another object. Do not include markdown, explanation, prose, or additional fields.",
                schema,
            ]
        )

    def _extract_content(self, stdout: bytes) -> str:
        text = stdout.decode("utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise AIProviderError("Tabnine CLI provider returned no output")

        envelope = self._parse_observed_json_envelope(lines)
        if isinstance(envelope, dict):
            if isinstance(envelope.get("response"), str):
                return envelope["response"]
            if isinstance(envelope.get("answer"), str):
                return envelope["answer"]

        return json.dumps(envelope)

    def _parse_observed_json_envelope(self, lines: list[str]) -> object:
        for index, line in enumerate(lines):
            if not line.lstrip().startswith("{"):
                continue
            candidate = chr(10).join(lines[index:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        raise AIProviderError("Tabnine CLI provider did not return a JSON response")
