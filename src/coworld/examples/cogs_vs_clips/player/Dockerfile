ARG PLAYER_RUNTIME_PLATFORM=linux/amd64
FROM --platform=${PLAYER_RUNTIME_PLATFORM} python:3.12-slim

RUN pip install --no-cache-dir \
    cogames

WORKDIR /app
COPY src/coworld/examples/cogs_vs_clips/player/policy_player.py /app/coworld_policy_player.py
ENV PYTHONPATH=/app

CMD ["python", "/app/coworld_policy_player.py"]
