"""Small provider-compatible client for the PA Compass LLM assistance layer."""

from datetime import datetime, timezone
import json
import os
import time
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import TypeAdapter, ValidationError

from pa_compass.models import (
    CasePacket,
    EvaluationResult,
    ExtractionResult,
    MissingItem,
    PolicyDefinition,
)
from pa_compass.prompts import (
    PROMPT_VERSION,
    build_extraction_messages,
    build_followup_messages,
    build_reason_messages,
)


class ModelOutputError(Exception):
    """Raised when an LLM request or its validated output fails."""

    def __init__(self, message: str, kind: str = "model") -> None:
        super().__init__(message)
        self.kind = kind


class _OutputParseError(Exception):
    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        load_dotenv()

        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv(
            "LLM_API_KEY"
        )
        if not self.api_key:
            raise ValueError(
                "No OpenAI API key found. Set OPENAI_API_KEY in .env or the "
                "environment."
            )
        self.model = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.last_stats: dict[str, Any] | None = None

    @staticmethod
    def _response_content(response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ModelOutputError("Model response did not contain message content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelOutputError("Model response contained empty message content")
        return content.strip()

    @staticmethod
    def _usage_value(usage: Any, *names: str) -> int:
        for name in names:
            if isinstance(usage, dict) and usage.get(name) is not None:
                return int(usage[name])
            value = getattr(usage, name, None)
            if value is not None:
                return int(value)
        return 0

    def _record_stats(
        self,
        node: str,
        input_tokens: int,
        output_tokens: int,
        latency_s: float,
        retries: int,
        schema_valid: bool,
    ) -> None:
        self.last_stats = {
            "node": node,
            "model": self.model,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_s": round(latency_s, 6),
            "retries": retries,
            "schema_valid": schema_valid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _run(
        self,
        node: str,
        messages: list[dict[str, str]],
        parser: Callable[[str], Any],
        correction: str,
        response_format: dict[str, str] | None = None,
    ) -> Any:
        started = time.perf_counter()
        input_tokens = 0
        output_tokens = 0
        last_error: Exception | None = None
        failure_kind = "model"

        for attempt in range(2):
            request_messages = messages
            if attempt:
                request_messages = [
                    *messages,
                    {"role": "user", "content": correction},
                ]
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": request_messages,
                    "temperature": 0,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format
                response = self.client.chat.completions.create(**kwargs)
                content = self._response_content(response)
                usage = getattr(response, "usage", None)
                input_tokens += self._usage_value(
                    usage, "prompt_tokens", "input_tokens"
                )
                output_tokens += self._usage_value(
                    usage, "completion_tokens", "output_tokens"
                )
                value = parser(content)
                self._record_stats(
                    node,
                    input_tokens,
                    output_tokens,
                    time.perf_counter() - started,
                    attempt,
                    attempt == 0,
                )
                return value
            except _OutputParseError as exc:
                last_error = exc
                failure_kind = exc.kind
            except ModelOutputError as exc:
                last_error = exc
                failure_kind = exc.kind
            except Exception as exc:  # Provider/network failures fail closed.
                last_error = exc
                failure_kind = "model"

        self._record_stats(
            node,
            input_tokens,
            output_tokens,
            time.perf_counter() - started,
            1,
            False,
        )
        message = str(last_error) if last_error else "Unknown model output failure"
        raise ModelOutputError(
            f"{node} failed after one retry: {message}", kind=failure_kind
        ) from last_error

    @staticmethod
    def _parse_extraction(content: str) -> ExtractionResult:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise _OutputParseError(
                f"Invalid JSON response during extraction: {exc.msg}", "model"
            ) from exc
        try:
            return ExtractionResult.model_validate(payload)
        except ValidationError as exc:
            raise _OutputParseError(
                f"Schema validation failed during extraction: {exc}", "schema"
            ) from exc

    @staticmethod
    def _parse_followup(content: str) -> list[str]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise _OutputParseError(
                f"Invalid JSON response during follow-up generation: {exc.msg}",
                "model",
            ) from exc
        try:
            return TypeAdapter(list[str]).validate_python(payload)
        except ValidationError as exc:
            raise _OutputParseError(
                f"Schema validation failed during follow-up generation: {exc}",
                "schema",
            ) from exc

    @staticmethod
    def _parse_reason(content: str) -> str:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = content
        try:
            result = TypeAdapter(str).validate_python(payload)
        except ValidationError as exc:
            raise _OutputParseError(
                f"Schema validation failed during reason summarization: {exc}",
                "schema",
            ) from exc
        if not result.strip():
            raise _OutputParseError(
                "Schema validation failed during reason summarization: empty string",
                "schema",
            )
        return result.strip()

    def extract_evidence(
        self, packet: CasePacket, policy: PolicyDefinition
    ) -> ExtractionResult:
        return self._run(
            "extract_evidence",
            build_extraction_messages(packet, policy),
            self._parse_extraction,
            "Correct the previous response. Return only valid JSON matching the "
            "ExtractionResult schema, with no markdown or commentary.",
            response_format={"type": "json_object"},
        )

    def generate_followup(
        self, missing_items: list[MissingItem], policy: PolicyDefinition
    ) -> list[str]:
        return self._run(
            "generate_followup",
            build_followup_messages(missing_items, policy),
            self._parse_followup,
            "Correct the previous response. Return only a JSON array of strings, "
            "one concise provider-facing question per missing requirement.",
        )

    def summarize_reason(self, assessment: EvaluationResult) -> str:
        return self._run(
            "summarize_reason",
            build_reason_messages(assessment),
            self._parse_reason,
            "Correct the previous response. Return only one short plain-English "
            "sentence, with no markdown or extra commentary.",
        )
