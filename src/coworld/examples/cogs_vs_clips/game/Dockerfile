ARG METTASCOPE_BUILDER_PLATFORM=linux/amd64
ARG GAME_RUNTIME_PLATFORM=linux/amd64
FROM --platform=${METTASCOPE_BUILDER_PLATFORM} emscripten/emsdk:4.0.15 AS mettascope-builder

ARG NIMBY_VERSION=0.1.26
ARG NIM_VERSION=2.2.6

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN ARCH="$(uname -m)" && \
    if [ "${ARCH}" = "aarch64" ]; then NIMBY_ARCH="Arm64"; else NIMBY_ARCH="X64"; fi && \
    curl -fsSL "https://github.com/treeform/nimby/releases/download/${NIMBY_VERSION}/nimby-Linux-${NIMBY_ARCH}" \
        -o /usr/local/bin/nimby && \
    chmod +x /usr/local/bin/nimby && \
    nimby use "${NIM_VERSION}" && \
    chmod +x /root/.nimby/nim/bin/nimble

ENV PATH="/root/.nimby/nim/bin:${PATH}"

WORKDIR /mettascope
COPY packages/mettagrid/nim/mettascope/mettascope.nimble /mettascope/mettascope.nimble
COPY packages/mettagrid/nim/mettascope/nimby.lock /mettascope/nimby.lock
RUN nimby sync -g nimby.lock
COPY packages/mettagrid/nim/mettascope/src /mettascope/src
COPY packages/mettagrid/nim/mettascope/data /mettascope/data
RUN nim c -d:emscripten -d:release src/mettascope.nim && \
    test -f dist/mettascope.html && \
    test -f dist/mettascope.js && \
    test -f dist/mettascope.wasm && \
    test -f dist/mettascope.data && \
    ls -lh dist/

FROM --platform=${GAME_RUNTIME_PLATFORM} python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi==0.115.5 \
    uvicorn[standard]==0.34.2 \
    mettagrid==0.26.17 \
    "cogsguard @ git+https://github.com/Metta-AI/cogame-cogsguard.git@3be7e391505a513d801318904b50ef15eed9644f"

WORKDIR /app
COPY packages/mettagrid/python/src/mettagrid/runner/live_episode.py /tmp/live_episode.py
RUN python - <<'PY'
from pathlib import Path
import shutil

import mettagrid

runner_dir = Path(mettagrid.__file__).parent / "runner"
shutil.copyfile("/tmp/live_episode.py", runner_dir / "live_episode.py")
PY
COPY --from=mettascope-builder /mettascope/dist /app/mettascope
COPY packages/coworld/src/coworld /app/coworld
COPY packages/coworld/src/coworld/examples/cogs_vs_clips/game/clients /app/clients
COPY packages/coworld/src/coworld/examples/cogs_vs_clips/game/server.py /app/server.py
ENV PYTHONPATH=/app

CMD ["python", "/app/server.py"]
