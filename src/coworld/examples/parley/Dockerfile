FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

RUN pip install --no-cache-dir httpx==0.28.1 pydantic==2.12.3 websockets==16.1.1
WORKDIR /opt/player
COPY --chmod=555 *.py ./coworld/examples/parley/
ARG PARLEY_OPERATOR_PROMPT="Play legal actions and maximize your score."
ARG PARLEY_INFERENCE="{}"
ENV PARLEY_OPERATOR_PROMPT=${PARLEY_OPERATOR_PROMPT} PARLEY_INFERENCE=${PARLEY_INFERENCE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
CMD ["python", "-m", "coworld.examples.parley.player"]
