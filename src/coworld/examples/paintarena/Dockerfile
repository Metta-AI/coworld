FROM python:3.12-slim

RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.34.2 websockets==15.0.1

WORKDIR /app
COPY game /app/game
COPY player /app/player

CMD ["python", "/app/game/server.py"]
