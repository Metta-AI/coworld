"""Private player exchanges, separate from game-owned acceptance and outcomes."""

import base64
import io
import zipfile
from typing import Literal
from uuid import UUID

from pydantic import AliasPath, BaseModel, ConfigDict, Field, JsonValue, model_validator

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
    top_p: Literal[1]
    reasoning: dict[Literal["effort"], Literal["none"]]
    chat_template_kwargs: dict[Literal["enable_thinking"], Literal[False]]
    max_tokens: int = Field(gt=0)
    response_format: dict[Literal["type"], Literal["json_object"]] | SchemaFormat
    stop: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)


class ChatResponse(BaseModel):
    model: str
    content: str = Field(min_length=1, validation_alias=AliasPath("choices", 0, "message", "content"))
    finish_reason: Literal["stop"] = Field(validation_alias=AliasPath("choices", 0, "finish_reason"))

    _single_choice = model_validator(mode="before")(validate_single_choice)


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
            output_tokens=self.request.max_tokens, temperature=self.request.temperature, stop=self.request.stop
        )
        if self.request.model_dump() != expected.request(self.request.model, self.request.messages):
            raise ValueError("Captured request differs from canonical inference settings")
        if self.http_status != 200:
            raise ValueError("Training requires a successful inference response")
        if base64.b64decode(self.response_body_b64, validate=True).decode("utf-8") != self.raw_response:
            raise ValueError("Captured response differs from its original bytes")
        response = ChatResponse.model_validate_json(self.raw_response)
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
