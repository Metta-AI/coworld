"""Private player exchanges, separate from game-owned acceptance and outcomes."""

import base64
import io
import zipfile
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from coworld.examples.parley.inference import InferenceSettings, Message, validate_single_choice


class ActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)
    name: Literal["parley_action"]
    schema_: dict[str, JsonValue] = Field(alias="schema")


class SchemaFormat(BaseModel):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)
    type: Literal["json_schema"]
    json_schema: ActionSchema


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=2)
    temperature: float = Field(ge=0, le=2)
    top_p: int | float = Field(gt=0, le=1)
    top_k: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)
    reasoning: dict[Literal["effort"], Literal["none", "high"]]
    chat_template_kwargs: dict[Literal["enable_thinking"], bool]
    max_tokens: int = Field(gt=0)
    custom_params: dict[Literal["thinking_budget"], int] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    response_format: dict[Literal["type"], Literal["json_object"]] | SchemaFormat
    stop: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    stop_regex: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    no_stop_trim: bool = Field(default=False, exclude_if=lambda value: not value)


class ChatResponse(BaseModel):
    model: str
    content: str = Field(min_length=1, validation_alias=AliasPath("choices", 0, "message", "content"))
    finish_reason: Literal["stop"] = Field(validation_alias=AliasPath("choices", 0, "finish_reason"))
    reasoning_content: str | None = Field(
        default=None, validation_alias=AliasPath("choices", 0, "message", "reasoning_content")
    )
    reasoning_tokens: StrictInt | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            AliasPath("usage", "reasoning_tokens"), AliasPath("usage", "completion_tokens_details", "reasoning_tokens")
        ),
    )

    _single_choice = model_validator(mode="before")(validate_single_choice)

    def validate_thinking(self, enabled: bool, thinking_budget: int | None = None) -> None:
        if enabled and (self.reasoning_content is None or not self.reasoning_content.strip()):
            raise ValueError("Thinking inference requires a separate, nonempty reasoning_content response")
        if not enabled and self.reasoning_content:
            raise ValueError("Nonthinking inference returned reasoning content")
        if thinking_budget is not None and (
            self.reasoning_tokens is None or not 0 < self.reasoning_tokens <= thinking_budget + 1
        ):
            # SGLang counts the closing </think> token in reasoning usage.
            raise ValueError("Bounded thinking requires reported token usage within its budget and closing marker")


class InferenceCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    protocol: Literal["parley.inference-capture.v1"] = "parley.inference-capture.v1"
    decision_id: str
    seat: int = Field(ge=0, le=4)
    request: ChatRequest
    raw_response: str
    response_body_b64: str
    http_status: int | None
    platform_call_id: UUID | None

    def completion(self) -> str:
        if isinstance(self.request.response_format, SchemaFormat):
            raise ValueError("Legal-action constrained captures are evaluation-only, not model-only training labels")
        expected = InferenceSettings(
            output_tokens=self.request.max_tokens,
            temperature=self.request.temperature,
            top_p=self.request.top_p,
            top_k=self.request.top_k,
            stop=self.request.stop,
            stop_regex=self.request.stop_regex,
            no_stop_trim=self.request.no_stop_trim,
            enable_thinking=self.request.chat_template_kwargs["enable_thinking"],
            thinking_budget=None
            if self.request.custom_params is None
            else self.request.custom_params["thinking_budget"],
        )
        if self.request.model_dump() != expected.request(self.request.model, self.request.messages):
            raise ValueError("Captured request differs from canonical inference settings")
        if self.http_status != 200:
            raise ValueError("Training requires a successful inference response")
        if base64.b64decode(self.response_body_b64, validate=True).decode("utf-8") != self.raw_response:
            raise ValueError("Captured response differs from its original bytes")
        response = ChatResponse.model_validate_json(self.raw_response)
        response.validate_thinking(expected.enable_thinking, expected.thinking_budget)
        if response.model != self.request.model:
            raise ValueError("Captured response model differs from its request")
        return response.content


def capture_archive(captures: list[InferenceCapture]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inference.jsonl", "".join(c.model_dump_json() + "\n" for c in captures))
    return buffer.getvalue()


def read_capture_archive(data: bytes) -> list[InferenceCapture]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("inference.jsonl")
        if info.file_size > 128 * 1024 * 1024:
            raise ValueError("Inference capture exceeds the input byte budget")
        rows = [InferenceCapture.model_validate_json(line) for line in archive.read(info).splitlines()]
    if len({(r.seat, r.decision_id) for r in rows}) != len(rows):
        raise ValueError("Player capture repeats a decision")
    return rows
