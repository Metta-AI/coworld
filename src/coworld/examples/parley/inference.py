"""Inference settings shared by the Parley player and its training consumers."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

CHAT_TEMPLATE_KWARGS = {"enable_thinking": False}


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class InferenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_tokens: int = Field(default=32768, gt=1)
    output_tokens: int = Field(default=300, gt=0)
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1, exclude_if=lambda value: value == 1)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1, exclude_if=lambda value: value is None)
    timeout_seconds: float = Field(default=40, gt=0)
    output_format: Literal["json", "text"] = "json"
    stop: list[str] = Field(default_factory=list)
    enable_thinking: bool = Field(default=False, exclude_if=lambda value: not value)
    thinking_budget: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_thinking_budget(self) -> "InferenceSettings":
        if self.thinking_budget is not None and (
            not self.enable_thinking or self.output_format != "json" or self.thinking_budget + 2 >= self.output_tokens
        ):
            raise ValueError("A thinking budget requires thinking JSON inference and room for the final action")
        return self

    def request(self, model: str, messages: list[Message]) -> dict[str, JsonValue]:
        request: dict[str, JsonValue] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "reasoning": {"effort": "high" if self.enable_thinking else "none"},
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
            "max_tokens": self.output_tokens,
        }
        if self.output_format == "json":
            request["response_format"] = {"type": "json_object"}
        if self.thinking_budget is not None:
            request["custom_params"] = {"thinking_budget": self.thinking_budget}
        if self.stop:
            request["stop"] = self.stop
        if self.seed is not None:
            request["seed"] = self.seed
        return request

    def server_arguments(
        self,
        model_path: Path,
        model: str,
        *,
        model_type: str,
        host: str = "127.0.0.1",
        port: int = 8000,
        tool_call_parser: str | None = None,
        reasoning_parser: str | None = None,
    ) -> list[str]:
        """Use the same SGLang model and decoding setup locally and in player pods."""
        arguments = [
            "--model-path",
            str(model_path),
            "--served-model-name",
            model,
            "--host",
            host,
            "--port",
            str(port),
            "--dtype",
            "bfloat16",
            "--context-length",
            str(self.context_tokens),
            "--mem-fraction-static",
            "0.8",
        ]
        if model_type == "qwen3_5":
            # Training exports the text backbone, without a vision encoder.
            arguments.append("--language-only")
        if tool_call_parser is not None:
            arguments.extend(["--tool-call-parser", tool_call_parser])
        if reasoning_parser is not None or self.enable_thinking:
            arguments.extend(["--reasoning-parser", reasoning_parser or "qwen3"])
        if self.thinking_budget is not None:
            arguments.append("--enable-strict-thinking")
        return arguments


def validate_single_choice(value: Any) -> dict[str, JsonValue]:
    """Validate the provider envelope before projecting its single answer into a model."""
    response = TypeAdapter(dict[str, JsonValue]).validate_python(value)
    if "choices" not in response:
        raise ValueError("Chat response must contain choices")
    TypeAdapter(tuple[dict[str, JsonValue]]).validate_python(response["choices"])
    if "usage" in response and response["usage"] is not None:
        TypeAdapter(dict[str, JsonValue]).validate_python(response["usage"])
    return response
