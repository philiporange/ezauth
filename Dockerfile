# ezAuth API image.
#
# Stage 1 builds the runtime dependencies into a virtualenv with a compiler
# available; stage 2 copies that virtualenv onto a clean slim base together
# with the application source, the migrations and alembic.ini. Development
# dependencies are never installed. The container runs as the unprivileged
# `ezauth` user and serves uvicorn on port 8000 with proxy headers trusted so
# that per-IP rate limiting sees the real client address behind a reverse
# proxy.

FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 997 ezauth \
    && useradd --system --uid 997 --gid ezauth --home-dir /app --no-create-home ezauth

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# The application resolves its static mounts relative to the working
# directory, so the source tree keeps its `src/ezauth/...` layout here.
COPY --chown=ezauth:ezauth alembic.ini /app/alembic.ini
COPY --chown=ezauth:ezauth alembic /app/alembic
COPY --chown=ezauth:ezauth src /app/src

USER ezauth

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"]

CMD ["uvicorn", "ezauth.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
