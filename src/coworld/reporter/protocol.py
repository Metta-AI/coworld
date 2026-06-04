"""WebSocket protocol messages for the reporter service.

A reporter is a persisted service that the platform wakes over a WebSocket. Unlike the per-episode bundle
runner it replaces, a reporter spans many episodes/rounds, fetches whatever inputs it needs over HTTPS, and
writes its output back over the same socket. These Pydantic models are the typed message shapes for that
`/report` channel; see `docs/roles/REPORTER.md` for the full contract.

The shape mirrors `commissioner/protocol.py`: every message is a JSON object with a `"type"` discriminator,
each model exposes `to_json()` (which stamps `type`), and `ReporterMessage.from_json` dispatches inbound
reporter messages back to their model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ReportTarget(BaseModel):
    """The entity a report request is about, echoed back on the reporter's output.

    `kind` is intentionally open (e.g. "episode", "round", "league", "policy_version") because a reporter
    service spans many entity types over its lifetime. `id` is the platform identifier for that entity.
    """

    kind: str = Field(min_length=1, description="Kind of entity this report is about, e.g. episode or round.")
    id: str = Field(min_length=1, description="Platform identifier of the target entity.")


class ReportRequest(BaseModel):
    """Platform -> reporter. The wake: produce output for `target`.

    The request carries only context, not inputs. The reporter fetches whatever it needs over HTTPS; `context`
    is an opaque bag of platform hints (known artifact URIs, league identifiers, etc.) the reporter may use or
    ignore. What the reporter does after waking is a black box to the platform.
    """

    request_id: str = Field(
        min_length=1, description="Platform-generated id, echoed on the matching output or failure."
    )
    target: ReportTarget = Field(description="Entity this report is about.")
    reason: str = Field(description="Why the platform woke the reporter, e.g. episode_completed or manual_refresh.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque platform hints (artifact URIs, ids); the reporter may fetch its own inputs instead.",
    )

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "report_request"
        return data


class Drain(BaseModel):
    """Platform -> reporter. Finish in-flight requests and exit cleanly (deploy, scale-to-zero, shutdown)."""

    reason: str = Field(description="Why the platform is draining the reporter, e.g. deploy or idle_scale_down.")

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "drain"
        return data


class ReportAccepted(BaseModel):
    """Reporter -> platform. Acknowledge a `report_request` before doing long work (also serves as liveness)."""

    request_id: str = Field(min_length=1, description="The accepted request's id.")

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "report_accepted"
        return data


class ReportOutput(BaseModel):
    """Reporter -> platform. The produced output, bound to the triggering request and target.

    `mime` must match the reporter's declared `output_format` in the manifest. `encoding` says how the payload
    is carried on the wire:

    - `text`   — `payload` is a plain string (e.g. Markdown).
    - `json`   — `payload` is an inline JSON value validated against the declared output-format schema.
    - `base64` — `payload` is binary bytes base64-encoded into a string.
    - `binary` — `payload` is omitted; the bytes are the **immediately following** WebSocket binary frame.

    The `binary` encoding avoids base64 inflation for large binary outputs (e.g. Parquet event logs). Because a
    raw binary frame carries no `request_id`, correlation lives entirely in this control message: a reporter MUST
    send a `binary`-encoded `report_output` and its trailing binary frame back-to-back, with no other frame
    interleaved on that connection between them. The platform attributes the next binary frame to the
    `request_id`/`target` named here.
    """

    request_id: str = Field(min_length=1, description="Id of the request this output answers.")
    target: ReportTarget = Field(description="Entity this output is about; echoes the request target.")
    mime: str = Field(min_length=1, description="MIME type of the payload; must match the declared output_format.")
    encoding: Literal["text", "json", "base64", "binary"] = Field(
        description=(
            "Wire representation of payload: text string, inline JSON value, base64-encoded binary, or binary "
            "(payload omitted; bytes follow as the next WebSocket binary frame)."
        ),
    )
    payload: Any = Field(
        default=None,
        description="The output itself, represented per `encoding`; omitted when `encoding` is `binary`.",
    )

    @model_validator(mode="after")
    def validate_payload_for_encoding(self) -> ReportOutput:
        if self.encoding == "binary":
            if self.payload is not None:
                raise ValueError(
                    "payload must be omitted when encoding is 'binary'; the bytes follow as a binary frame"
                )
        elif self.payload is None:
            raise ValueError("payload is required for 'text', 'json', and 'base64' encodings")
        return self

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "report_output"
        return data


class ReportFailed(BaseModel):
    """Reporter -> platform. The reporter could not produce output for a request."""

    request_id: str = Field(min_length=1, description="Id of the request that failed.")
    target: ReportTarget = Field(description="Entity the failed request was about.")
    error: str = Field(description="Human-readable failure reason.")

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "report_failed"
        return data


PlatformMessage = ReportRequest | Drain

ReporterMessageType = ReportAccepted | ReportOutput | ReportFailed

_REPORTER_MESSAGE_TYPES: dict[str, type[ReporterMessageType]] = {
    "report_accepted": ReportAccepted,
    "report_output": ReportOutput,
    "report_failed": ReportFailed,
}


class ReporterMessage:
    @staticmethod
    def from_json(data: dict[str, Any]) -> ReporterMessageType:
        msg_type = data["type"]
        cls = _REPORTER_MESSAGE_TYPES.get(msg_type)
        if cls is None:
            raise ValueError(f"Unknown reporter message type: {msg_type!r}")
        return cls.model_validate({key: value for key, value in data.items() if key != "type"})
