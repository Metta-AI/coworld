"""Play exact Parley windows with owned, bounded native inference."""

import asyncio
import base64
import json
import os
import signal
import sys
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote, urlparse

import httpx
import websockets
from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StrictBool,
    StrictInt,
    TypeAdapter,
    model_validator,
)

from coworld.examples.parley.evidence import ChatRequest, InferenceCapture, capture_archive
from coworld.examples.parley.inference import InferenceSettings, Message, validate_single_choice


class PrivateModel(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class Packet(PrivateModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PromptInput(Packet):
    system: str
    user: str


class LegalAction(Packet):
    shoot: str
    aim: Literal["head", "hip"] | None = None


class Observation(Packet):
    phase: Literal["shot", "reaction"]
    observation: dict[str, JsonValue]
    input: PromptInput
    legalActions: list[LegalAction]
    actionSchema: dict[str, JsonValue] | None = None
    extras: dict[str, JsonValue]


class Transport(Packet):
    budget_ms: StrictInt = Field(gt=0)
    cleanup_budget_ms: StrictInt = Field(ge=0)


class Decision(Packet):
    type: Literal["decision"]
    decision_id: str = Field(min_length=1)
    observation: Observation
    transport: Transport


class PublishedDecision(PrivateModel):
    type: Literal["observation"]
    id: int
    phase: Literal["shot", "reaction"]
    input: PromptInput
    legalActions: list[LegalAction]


class Stop(Packet):
    type: Literal["stop"]
    stop_id: str = Field(min_length=1)
    decision_id: str | None
    reason: Literal["interrupted", "episode_deadline", "terminal"]
    cleanup_budget_ms: StrictInt = Field(ge=0)


class PrivateAttempt(Packet):
    """Player wire evidence; acceptance and parsed actions belong to the game."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)
    attempt_id: str
    policy: str = "parley-qwen-native"
    origin: Literal["model"] = "model"
    model: str
    prompt: list[dict[str, str]]
    request: dict[str, JsonValue]
    decoder: dict[str, JsonValue]
    response: str | None = None
    raw_response: str | None = None
    response_headers: dict[str, str] | None = None
    provider_request_id: str | None = None
    response_body_b64: str | None = None
    response_headers_b64: str | None = None
    response_complete: StrictBool | None = None
    response_reader_joined: StrictBool | None = None
    http_status: StrictInt | None = None
    platform_call_id: str | None = None
    rejection_reason: str | None = None
    model_identity: str | None = None
    tokenizer_identity: str | None = None
    chat_template_sha256: str | None = None
    stop_reason: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_token_ids: list[int] | None = None
    sampled_token_ids: list[int] | None = None
    behavior_logprobs: list[float] | None = None


class UnitSamplingEvidence(Packet):
    policy_revision: str
    tokenizer_revision: str
    chat_template: str
    enable_thinking: Literal[False]
    max_new_tokens: StrictInt = Field(gt=0)
    max_sequence_length: StrictInt = Field(gt=0)
    sampling_seed: StrictInt
    eos_token_ids: list[StrictInt]
    prompt_token_ids: list[StrictInt] = Field(min_length=1)
    completion_token_ids: list[StrictInt] = Field(min_length=1)
    behavior_log_probs: list[float]
    stop_reason: Literal["eos", "length"]
    response: str
    sampling: Literal["full_softmax_temperature_one"]


class TemperedSamplingEvidence(UnitSamplingEvidence):
    sampling: Literal["full_softmax"]
    temperature: FiniteFloat = Field(gt=0, le=2)


SamplingEvidence = Annotated[UnitSamplingEvidence | TemperedSamplingEvidence, Field(discriminator="sampling")]


class Completion(PrivateModel):
    model: str
    content: str = Field(validation_alias=AliasPath("choices", 0, "message", "content"))
    finish_reason: Literal["stop"] = Field(validation_alias=AliasPath("choices", 0, "finish_reason"))
    prompt_tokens: StrictInt | None = Field(default=None, ge=0, validation_alias=AliasPath("usage", "prompt_tokens"))
    completion_tokens: StrictInt | None = Field(
        default=None, ge=0, validation_alias=AliasPath("usage", "completion_tokens")
    )
    sampling_evidence: SamplingEvidence | None = None

    @model_validator(mode="before")
    @classmethod
    def response_fields(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        response = validate_single_choice(value)
        if "usage" in response and response["usage"] is not None:
            usage = TypeAdapter(dict[str, JsonValue]).validate_python(response["usage"])
            if any(key not in usage or usage[key] is None for key in ("prompt_tokens", "completion_tokens")):
                raise ValueError("Usage must contain both token counts")
        return response


class Player:
    def __init__(self, socket: websockets.ClientConnection, client: httpx.AsyncClient) -> None:
        self.socket = socket
        self.client = client
        self.settings = InferenceSettings.model_validate_json(os.environ.get("PARLEY_INFERENCE", "{}"))
        self.captures: list[InferenceCapture] = []
        self.native = False
        self.slot = -1
        self.decision_id: str | None = None
        self.attempt: PrivateAttempt | None = None
        self.worker: asyncio.Task[None] | None = None
        self.stopped = False
        self.cleanup_budget_ms = 0
        self.cleanup_deadline: float | None = None
        self.reader_cleanup: asyncio.Task[None] | None = None
        self.evidence_send: asyncio.Task[None] | None = None

    def begin_cleanup(self, budget_ms: int) -> float:
        deadline = asyncio.get_running_loop().time() + budget_ms / 1000
        self.cleanup_deadline = deadline if self.cleanup_deadline is None else min(self.cleanup_deadline, deadline)
        return self.cleanup_deadline

    async def join_owned(self, deadline: float) -> bool:
        if self.worker is not None and not self.worker.done() and self.worker.cancelling() == 0:
            self.worker.cancel()
        tasks = {task for task in (self.worker, self.reader_cleanup, self.evidence_send) if task is not None}
        if not tasks:
            return True
        await asyncio.wait(tasks, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        tasks = {task for task in (self.worker, self.reader_cleanup, self.evidence_send) if task is not None}
        if any(not task.done() for task in tasks):
            await asyncio.wait(tasks, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        return all(task.done() for task in tasks)

    async def publish_attempt(self, decision_id: str, attempt: PrivateAttempt) -> None:
        await self.socket.send(
            json.dumps(
                {"type": "attempt_started", "decision_id": decision_id, "training_attempt": attempt.model_dump()}
            )
        )

    async def answer(self, decision: Decision | PublishedDecision, deadline: float) -> None:
        native = isinstance(decision, Decision)
        view = decision.observation if native else decision
        decision_id = decision.decision_id if native else str(decision.id)
        cleanup_budget_ms = decision.transport.cleanup_budget_ms if native else 1000
        if "PARLEY_ENDPOINT" in os.environ:
            endpoint = os.environ["PARLEY_ENDPOINT"]
            model = os.environ["PARLEY_MODEL"]
        else:
            endpoint = os.environ["COWORLD_LLM_ENDPOINT"]
            model = os.environ["COWORLD_LLM_MODEL"]
        messages = [
            Message(role="system", content=view.input.system),
            Message(role="user", content=view.input.user),
        ]
        request = self.settings.request(model, messages)
        decoder = {key: value for key, value in request.items() if key not in {"model", "messages"}}
        attempt = PrivateAttempt(
            attempt_id=decision_id + "-model",
            model=model,
            prompt=[message.model_dump() for message in messages],
            request=request,
            decoder=decoder,
        )
        self.attempt = attempt
        loop = asyncio.get_running_loop()
        started = loop.time()
        if native:
            async with asyncio.timeout_at(deadline):
                await self.publish_attempt(decision_id, attempt)
        headers = {
            "Accept-Encoding": "identity",
            "X-Coworld-Player-Slot": str(self.slot),
        }
        if "PARLEY_API_KEY_ENV" in os.environ:
            headers["Authorization"] = "Bearer " + os.environ[os.environ["PARLEY_API_KEY_ENV"]]
        body = bytearray()
        sent_action = False
        try:
            async with asyncio.timeout_at(deadline):
                response = await self.client.send(
                    self.client.build_request(
                        "POST",
                        endpoint.rstrip("/") + os.environ.get("PARLEY_COMPLETION_PATH", "/v1/chat/completions"),
                        json=request,
                        headers=headers,
                    ),
                    stream=True,
                )
                attempt.response_reader_joined = False
                try:
                    attempt.http_status = response.status_code
                    attempt.response_headers = dict(response.headers)
                    attempt.response_complete = False
                    controlled = {
                        "x-softmax-llm-call-id",
                        "request-id",
                        "x-request-id",
                        "x-coworld-checkpoint-sha256",
                        "x-coworld-tokenizer-sha256",
                        "x-coworld-chat-template-sha256",
                    }
                    names = [name.decode("ascii").lower() for name, _ in response.headers.raw]
                    if any(names.count(name) > 1 for name in controlled):
                        raise ValueError("Duplicate native identity header")
                    attempt.platform_call_id = response.headers.get("X-Softmax-Llm-Call-Id")
                    request_id = response.headers.get("request-id")
                    alternate_id = response.headers.get("x-request-id")
                    if request_id is not None and alternate_id is not None and request_id != alternate_id:
                        raise ValueError("Conflicting native request identity headers")
                    attempt.provider_request_id = request_id if request_id is not None else alternate_id
                    attempt.model_identity = response.headers.get("X-Coworld-Checkpoint-Sha256")
                    attempt.tokenizer_identity = response.headers.get("X-Coworld-Tokenizer-Sha256")
                    attempt.chat_template_sha256 = response.headers.get("X-Coworld-Chat-Template-Sha256")
                    if native:
                        await self.publish_attempt(decision_id, attempt)
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > int(os.environ.get("PARLEY_MAX_RESPONSE_BYTES", "4194304")):
                            raise ValueError("Native inference response exceeds player byte budget")
                    attempt.response_complete = True
                finally:
                    self.reader_cleanup = asyncio.create_task(response.aclose())
                    cleanup_deadline = deadline if attempt.response_complete else self.begin_cleanup(cleanup_budget_ms)
                    done, _ = await asyncio.wait(
                        {self.reader_cleanup},
                        timeout=max(0, cleanup_deadline - loop.time()),
                    )
                    attempt.response_reader_joined = bool(done) and self.reader_cleanup.exception() is None
                if not attempt.response_reader_joined:
                    raise TimeoutError("Native response reader did not join within cleanup budget")
                raw = bytes(body).decode("utf-8")
                attempt.raw_response = raw
                if response.status_code != 200:
                    raise ValueError(f"Native inference failed ({response.status_code})")
                completion = Completion.model_validate_json(raw)
                attempt.model = completion.model
                attempt.response = completion.content
                attempt.stop_reason = completion.finish_reason
                attempt.input_tokens = completion.prompt_tokens
                attempt.output_tokens = completion.completion_tokens
                if completion.sampling_evidence is not None:
                    sample = completion.sampling_evidence
                    if (
                        sample.response != attempt.response
                        or len(sample.completion_token_ids) != len(sample.behavior_log_probs)
                        or sample.max_new_tokens != decoder["max_tokens"]
                        or len(sample.prompt_token_ids) + sample.max_new_tokens > sample.max_sequence_length
                        or len(sample.completion_token_ids) > sample.max_new_tokens
                        or any(
                            token < 0
                            for token in sample.prompt_token_ids + sample.completion_token_ids + sample.eos_token_ids
                        )
                        or any(probability > 0 for probability in sample.behavior_log_probs)
                        or any(token in sample.eos_token_ids for token in sample.completion_token_ids[:-1])
                        or ((sample.completion_token_ids[-1] in sample.eos_token_ids) != (sample.stop_reason == "eos"))
                        or (
                            sample.stop_reason == "length" and len(sample.completion_token_ids) != sample.max_new_tokens
                        )
                    ):
                        raise ValueError("Native sampling evidence differs from served response")
                    if self.settings.temperature != (
                        sample.temperature if isinstance(sample, TemperedSamplingEvidence) else 1.0
                    ):
                        raise ValueError("Sampled response differs from requested frozen decoder")
                    attempt.prompt_token_ids = sample.prompt_token_ids
                    attempt.sampled_token_ids = sample.completion_token_ids
                    attempt.behavior_logprobs = sample.behavior_log_probs
                    attempt.stop_reason = sample.stop_reason
                # The game owns legality and rejected-action evidence; forward the complete proposal unchanged.
                action = TypeAdapter(dict[str, JsonValue], config=ConfigDict(hide_input_in_errors=True)).validate_json(
                    attempt.response
                )
                attempt.latency_ms = (loop.time() - started) * 1000
                frame = (
                    {
                        "type": "action",
                        "decision_id": decision_id,
                        "action": action,
                        "source": "llm",
                        "training_attempt": attempt.model_dump(),
                    }
                    if native
                    else {"type": "action", "id": decision.id, "action": action}
                )
                await self.socket.send(json.dumps(frame))
                sent_action = True
        finally:
            self.capture(decision_id, request, bytes(body), attempt)
            if native and not sent_action:
                failure = sys.exception()
                if failure is not None:
                    attempt.rejection_reason = type(failure).__name__
                attempt.latency_ms = (loop.time() - started) * 1000
                self.evidence_send = asyncio.create_task(self.publish_attempt(decision_id, attempt))
                cleanup_deadline = self.begin_cleanup(cleanup_budget_ms)
                done, pending = await asyncio.wait({self.evidence_send}, timeout=max(0, cleanup_deadline - loop.time()))
                if pending:
                    self.evidence_send.cancel()
                if done:
                    self.evidence_send.exception()

    def capture(self, decision_id: str, request: dict[str, JsonValue], body: bytes, attempt: PrivateAttempt) -> None:
        self.captures.append(
            InferenceCapture(
                decision_id=decision_id,
                seat=self.slot,
                request=ChatRequest.model_validate(request),
                response_body_b64=base64.b64encode(body).decode("ascii"),
                raw_response=body.decode("utf-8", errors="replace"),
                http_status=attempt.http_status,
                platform_call_id=attempt.platform_call_id,
            )
        )

    async def upload_captures(self) -> None:
        archive = capture_archive(self.captures)
        target = os.environ["COWORLD_PLAYER_ARTIFACT_UPLOAD_URL"]
        uri = urlparse(target)
        if uri.scheme == "file":
            path = Path(unquote(uri.path))
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(archive)
            temporary.chmod(0o600)
            temporary.replace(path)
        elif uri.scheme in {"http", "https"}:
            response = await self.client.put(target, content=archive, headers={"Content-Type": "application/zip"})
            response.raise_for_status()
        else:
            raise ValueError("Unsupported player artifact URI")

    async def confirm_evidence(self, stop_id: str | None) -> None:
        async with asyncio.timeout_at(self.cleanup_deadline):
            await self.socket.send(
                json.dumps(
                    {
                        "type": "stopped",
                        "stop_id": stop_id,
                        "decision_id": self.decision_id,
                        "worker_status": "joined" if self.worker is not None else "no_active_call",
                        "attempts": [self.attempt.model_dump()] if self.attempt is not None else [],
                    }
                )
            )
            while True:
                raw = await self.socket.recv()
                packet = TypeAdapter(dict[str, JsonValue], config=ConfigDict(hide_input_in_errors=True)).validate_json(
                    raw
                )
                if packet == {"type": "evidence_received", "decision_id": self.decision_id, "stop_id": stop_id}:
                    return

    async def stop(self, packet: Stop) -> None:
        if packet.decision_id != self.decision_id:
            raise ValueError("Stop identity differs from owned decision")
        self.stopped = True
        if not await self.join_owned(self.begin_cleanup(packet.cleanup_budget_ms)):
            raise TimeoutError("Owned inference did not join within cleanup budget")
        await self.confirm_evidence(packet.stop_id)
        if self.worker is not None and not self.worker.cancelled():
            self.worker.result()

    async def run(self) -> None:
        registration = json.dumps(
            {
                "type": "register",
                "control": "external",
                "prompt": os.environ["PARLEY_OPERATOR_PROMPT"],
            }
        )
        await self.socket.send(registration)
        try:
            async with asyncio.TaskGroup() as workers:
                async for raw in self.socket:
                    if not isinstance(raw, str):
                        raise ValueError("Parley requires JSON text frames")
                    packet = TypeAdapter(
                        dict[str, JsonValue], config=ConfigDict(hide_input_in_errors=True)
                    ).validate_json(raw)
                    if packet["type"] == "welcome":
                        self.slot = TypeAdapter(
                            StrictInt, config=ConfigDict(hide_input_in_errors=True)
                        ).validate_python(packet["slot"])
                        await self.socket.send(registration)
                    elif packet["type"] == "observation":
                        self.cleanup_budget_ms = 1000
                        await self.answer(
                            PublishedDecision.model_validate(packet),
                            asyncio.get_running_loop().time() + self.settings.timeout_seconds,
                        )
                    elif packet["type"] == "decision":
                        self.native = True
                        received_at = asyncio.get_running_loop().time()
                        if self.stopped or self.slot < 0:
                            raise ValueError("Decision arrived outside active seated player lifetime")
                        if self.worker is not None:
                            if not await self.join_owned(self.begin_cleanup(self.cleanup_budget_ms)):
                                raise TimeoutError("Previous inference did not join before next decision")
                            if not self.worker.cancelled():
                                self.worker.result()
                        decision = Decision.model_validate(packet)
                        self.decision_id = decision.decision_id
                        self.attempt = None
                        self.cleanup_budget_ms = decision.transport.cleanup_budget_ms
                        self.cleanup_deadline = None
                        self.reader_cleanup = None
                        self.evidence_send = None
                        self.worker = workers.create_task(
                            self.answer(decision, received_at + decision.transport.budget_ms / 1000)
                        )
                    elif packet["type"] == "stop":
                        await self.stop(Stop.model_validate(packet))
                        return
                    elif packet["type"] == "final":
                        if self.native and not self.stopped:
                            raise ValueError("Final arrived before owned worker stop acknowledgement")
                        return
                    elif packet["type"] != "state":
                        raise ValueError("Unknown Parley player frame")
                raise RuntimeError("Parley socket closed before final result")
        finally:
            cleanup_deadline = self.begin_cleanup(self.cleanup_budget_ms)
            if not await self.join_owned(cleanup_deadline):
                raise TimeoutError("Owned player work did not join within cleanup budget")
            if self.native and not self.stopped and self.decision_id is not None:
                await self.confirm_evidence(None)
            if "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL" in os.environ:
                # Optional artifact I/O starts only after gameplay and native evidence acknowledgements.
                upload = asyncio.create_task(self.upload_captures())
                done, pending = await asyncio.wait(
                    {upload}, timeout=max(0, cleanup_deadline - asyncio.get_running_loop().time())
                )
                if pending:
                    upload.cancel()
                    await asyncio.gather(upload, return_exceptions=True)
                    print("Player artifact upload failed: cleanup deadline", file=sys.stderr)
                elif done and upload.exception() is not None:
                    print(f"Player artifact upload failed: {type(upload.exception()).__name__}", file=sys.stderr)


async def play() -> None:
    loop = asyncio.get_running_loop()
    # Serving connections may expire between turns; each decision owns a fresh HTTP connection.
    client = httpx.AsyncClient(timeout=None, limits=httpx.Limits(max_keepalive_connections=0))
    cleanup_deadline = loop.time() + 5
    try:
        socket = await websockets.connect(os.environ["COWORLD_PLAYER_WS_URL"], ping_timeout=None, close_timeout=1)
        try:
            player = Player(socket, client)
            task = asyncio.create_task(player.run())
            for requested in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(requested, lambda: task.cancelling() == 0 and task.cancel())
            try:
                await task
            finally:
                cleanup_deadline = player.begin_cleanup(player.cleanup_budget_ms)
                for requested in (signal.SIGTERM, signal.SIGINT):
                    loop.remove_signal_handler(requested)
        finally:
            closing = asyncio.create_task(socket.close())
            done, pending = await asyncio.wait({closing}, timeout=max(0, cleanup_deadline - loop.time()))
            if pending:
                closing.cancel()
                socket.transport.abort()
                raise TimeoutError("Owned game socket did not close within cleanup budget")
            closing.result()
    finally:
        closing = asyncio.create_task(client.aclose())
        done, pending = await asyncio.wait({closing}, timeout=max(0, cleanup_deadline - loop.time()))
        if pending:
            closing.cancel()
            raise TimeoutError("Owned HTTP client did not close within cleanup budget")
        closing.result()


if __name__ == "__main__":
    owned_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(owned_loop)
    try:
        owned_loop.run_until_complete(play())
    finally:
        owned_loop.close()
