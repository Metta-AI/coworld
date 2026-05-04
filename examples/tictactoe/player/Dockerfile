FROM python:3.12-slim

RUN pip install --no-cache-dir websockets==15.0.1

WORKDIR /app
COPY player.py /app/player.py

CMD ["python", "/app/player.py"]
