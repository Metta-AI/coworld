from __future__ import annotations

import uvicorn
from fastapi import FastAPI, WebSocket

from coworld.commissioner.protocol import (
    EpisodeRequest,
    RoundComplete,
    RoundStart,
    ScheduleEpisodes,
    ScheduleRoundsRequest,
    ScheduleRoundsResponse,
)

app = FastAPI()


def message_payload(message: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in message.items() if key != "type"}


def opening_schedule(round_start: RoundStart) -> ScheduleEpisodes:
    variant = round_start.variants[0]
    entrants = [membership.policy_version_id for membership in round_start.memberships[:2]]
    if len(entrants) < 2:
        return ScheduleEpisodes(episodes=[])
    return ScheduleEpisodes(
        episodes=[
            EpisodeRequest(
                request_id=f"{round_start.round_id}-episode-0",
                variant_id=variant.id,
                policy_version_ids=entrants,
            )
        ]
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/round")
async def round_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    message = await websocket.receive_json()
    message_type = message["type"]

    if message_type == "schedule_rounds_request":
        ScheduleRoundsRequest.model_validate(message_payload(message))
        await websocket.send_json(ScheduleRoundsResponse(rounds=[]).to_json())
        await websocket.close()
        return

    if message_type != "round_start":
        raise ValueError(f"Unsupported commissioner message: {message_type}")

    round_start = RoundStart.model_validate(message_payload(message))
    schedule = opening_schedule(round_start)
    if schedule.episodes:
        await websocket.send_json(schedule.to_json())

    while True:
        event = await websocket.receive_json()
        event_type = event["type"]
        if event_type in {"episode_result", "episode_failed"}:
            await websocket.send_json(RoundComplete().to_json())
            await websocket.close()
            return
        if event_type == "round_abort":
            await websocket.close()
            return


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
