FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pydantic
COPY reporter.py /app/reporter.py

CMD ["python", "/app/reporter.py"]
