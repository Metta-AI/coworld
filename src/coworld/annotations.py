"""Dedicated optional episode annotations, independent of logs and game protocols."""

from __future__ import annotations

import json
from typing import BinaryIO, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic_core import SchemaValidator, core_schema

ANNOTATIONS_TARGETS_ENV = "PLAYER_EPISODE_ANNOTATIONS_URLS"
ANNOTATIONS_MEDIA_TYPE = "application/x-ndjson"
ANNOTATIONS_MAX_BYTES = 2 * 1024 * 1024
ANNOTATIONS_MAX_EVENTS = 1000
ANNOTATION_MAX_BYTES = 2 * 1024


class EpisodeAnnotation(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    schema_version: Literal[1] = 1
    time: float = Field(description="Coordinate in the game's time system.")
    kind: str = Field(min_length=1, max_length=128, description="Purpose, such as decision, intent, or prediction.")
    function: str = Field(min_length=1, max_length=256, description="Operation being described.")
    args: dict[str, JsonValue] = Field(description="Game-specific operation parameters.")
    message: str | None = Field(default=None, description="Optional explanation.")
    actor: str | None = Field(default=None, description="Optional game entity identifier.")
    end_time: float | None = Field(default=None, description="Exclusive end coordinate of an interval.")

    @model_validator(mode="after")
    def valid_interval(self) -> EpisodeAnnotation:
        if self.end_time is not None and self.end_time < self.time:
            raise ValueError("end_time must be at least time")
        json.dumps(self.model_dump(), allow_nan=False)
        return self


_annotation_validator = SchemaValidator(core_schema.json_schema(EpisodeAnnotation.__pydantic_core_schema__))


def annotation_file_error(source: BinaryIO) -> str | None:
    """Validate without retaining the file; restore the stream for upload afterward."""
    total = 0
    line_number = 0
    try:
        while line := source.readline(ANNOTATION_MAX_BYTES + 1):
            line_number += 1
            total += len(line)
            if line_number > ANNOTATIONS_MAX_EVENTS:
                return "Annotation file exceeds 1000 records"
            if total > ANNOTATIONS_MAX_BYTES:
                return "Annotation file exceeds 2 MiB"
            if len(line) > ANNOTATION_MAX_BYTES:
                return f"Annotation record {line_number} exceeds 2 KiB"
            if not line.endswith(b"\n"):
                return f"Annotation record {line_number} is not newline-terminated"
            if not _annotation_validator.isinstance_python(line):
                return f"Invalid annotation record {line_number}"
        return None
    finally:
        source.seek(0)


def read_annotations(source: BinaryIO, *, participant_slot: int, first_seq: int = 0) -> Iterator[bytes]:
    for seq, line in enumerate(source, start=first_seq):
        if seq - first_seq >= ANNOTATIONS_MAX_EVENTS:
            raise ValueError("Annotation file exceeds 1000 records")
        if len(line) > ANNOTATION_MAX_BYTES or not line.endswith(b"\n"):
            raise ValueError("Annotation record exceeds 2 KiB or is not newline-terminated")
        annotation = EpisodeAnnotation.model_validate_json(line)
        annotation = annotation.model_copy(update={"participant_slot": participant_slot, "seq": seq})
        yield annotation.model_dump_json(exclude_none=True).encode() + b"\n"
