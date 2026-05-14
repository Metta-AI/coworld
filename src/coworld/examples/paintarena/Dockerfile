FROM docker.io/library/python:3.12-slim

RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.34.2 websockets==15.0.1

ENV PYTHONPATH=/app
WORKDIR /app

# Mirror the source-tree layout so absolute imports
# (`coworld.examples.paintarena.*`) resolve identically here and in tests.
# The `coworld` and `coworld.examples` packages contribute nothing else to
# the runtime image, so empty stub __init__.py files suffice.
RUN mkdir -p /app/coworld/examples && \
    touch /app/coworld/__init__.py /app/coworld/examples/__init__.py

COPY __init__.py /app/coworld/examples/paintarena/__init__.py
COPY shared /app/coworld/examples/paintarena/shared
COPY game /app/coworld/examples/paintarena/game
COPY player /app/coworld/examples/paintarena/player

CMD ["python", "-m", "coworld.examples.paintarena.game.server"]
