FROM python:3.12-slim

RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.34.2

WORKDIR /app
COPY clients /app/clients
COPY server.py /app/server.py

CMD ["python", "/app/server.py"]
