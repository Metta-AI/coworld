import pytest

from coworld.reporter.protocol import (
    Drain,
    ReportAccepted,
    ReporterMessage,
    ReportFailed,
    ReportOutput,
    ReportRequest,
    ReportTarget,
)


def test_report_request_serializes_with_message_type() -> None:
    request = ReportRequest(
        request_id="req_001",
        target=ReportTarget(kind="episode", id="ereq_abc"),
        reason="episode_completed",
        context={"results_uri": "https://example.com/results.json"},
    )

    data = request.to_json()

    assert data["type"] == "report_request"
    assert data["target"] == {"kind": "episode", "id": "ereq_abc"}
    assert data["context"]["results_uri"] == "https://example.com/results.json"


def test_drain_serializes_with_message_type() -> None:
    assert Drain(reason="deploy").to_json() == {"type": "drain", "reason": "deploy"}


def test_reporter_message_parses_report_output() -> None:
    parsed = ReporterMessage.from_json(
        {
            "type": "report_output",
            "request_id": "req_001",
            "target": {"kind": "episode", "id": "ereq_abc"},
            "mime": "text/markdown",
            "encoding": "text",
            "payload": "# Recap\n\nBlue held 62% of territory.",
        }
    )

    assert isinstance(parsed, ReportOutput)
    assert parsed.target == ReportTarget(kind="episode", id="ereq_abc")
    assert parsed.encoding == "text"
    assert parsed.to_json()["type"] == "report_output"


def test_reporter_message_parses_accepted_and_failed() -> None:
    accepted = ReporterMessage.from_json({"type": "report_accepted", "request_id": "req_001"})
    assert accepted == ReportAccepted(request_id="req_001")

    failed = ReporterMessage.from_json(
        {
            "type": "report_failed",
            "request_id": "req_001",
            "target": {"kind": "round", "id": "round_9"},
            "error": "results artifact not yet available",
        }
    )
    assert isinstance(failed, ReportFailed)
    assert failed.error == "results artifact not yet available"


def test_report_output_rejects_unknown_encoding() -> None:
    with pytest.raises(ValueError):
        ReportOutput.model_validate(
            {
                "request_id": "req_001",
                "target": {"kind": "episode", "id": "ereq_abc"},
                "mime": "application/json",
                "encoding": "protobuf",
                "payload": {},
            }
        )


def test_report_output_binary_omits_payload() -> None:
    parsed = ReporterMessage.from_json(
        {
            "type": "report_output",
            "request_id": "req_002",
            "target": {"kind": "episode", "id": "ereq_abc"},
            "mime": "application/vnd.apache.parquet",
            "encoding": "binary",
        }
    )

    assert isinstance(parsed, ReportOutput)
    assert parsed.encoding == "binary"
    assert parsed.payload is None


def test_report_output_binary_rejects_inline_payload() -> None:
    with pytest.raises(ValueError, match="payload must be omitted when encoding is 'binary'"):
        ReportOutput(
            request_id="req_002",
            target=ReportTarget(kind="episode", id="ereq_abc"),
            mime="application/vnd.apache.parquet",
            encoding="binary",
            payload="not-allowed",
        )


def test_report_output_non_binary_requires_payload() -> None:
    with pytest.raises(ValueError, match="payload is required"):
        ReportOutput(
            request_id="req_002",
            target=ReportTarget(kind="episode", id="ereq_abc"),
            mime="text/markdown",
            encoding="text",
        )


def test_unknown_reporter_message_type_fails() -> None:
    with pytest.raises(ValueError, match="Unknown reporter message type"):
        ReporterMessage.from_json({"type": "bogus"})
