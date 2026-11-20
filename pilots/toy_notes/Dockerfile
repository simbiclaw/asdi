FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TOY_NOTES_DB=/data/toy_notes.sqlite3

WORKDIR /app
COPY src/ /app/src/

RUN mkdir -p /data && chown -R 10001:10001 /data
USER 10001:10001
EXPOSE 8080

CMD ["python3", "-m", "toy_notes.server", "--db", "/data/toy_notes.sqlite3", "--host", "0.0.0.0", "--port", "8080"]
