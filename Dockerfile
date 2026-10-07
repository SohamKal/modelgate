FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/modelgate/.venv/bin:$PATH"

WORKDIR /srv/modelgate

RUN pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev --no-cache

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "scripts.start_gateway"]
