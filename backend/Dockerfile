# syntax=docker/dockerfile:1.7
# Two targets share one dependency stage:
#   api    — FastAPI (no ffmpeg)
#   worker — RQ worker with ffmpeg for the media (TTS/mixing) pipeline
# Layer order matters: everything slow (ffmpeg, Python deps) comes before `COPY . .`,
# so a code change only rebuilds the last, cheap layer.
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# /media is the shared volume for generated audio, /geoip the IP → place database (see
# docker-compose.yml): a new named volume copies the folder's owner from the image.
RUN useradd --create-home --uid 1000 app && mkdir -p /code /media /geoip && chown app:app /code /media /geoip

WORKDIR /code

# Python dependencies only (`package = false`), rebuilt when pyproject.toml / uv.lock change.
FROM runtime AS deps

# uv for fast, reproducible installs (versions pinned in uv.lock)
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM runtime AS api
COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app . .
# The commit this image was built from (deploy.sh passes it), shown on the console's System page.
ARG GIT_SHA=unknown
ENV APP_VERSION=$GIT_SHA
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
# Independent of the source code, so it stays cached; the apt cache mounts keep the downloaded
# .deb files even when this layer is rebuilt (e.g. after a base image update).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg
COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app . .
ARG GIT_SHA=unknown
ENV APP_VERSION=$GIT_SHA
USER app
CMD ["python", "-m", "app.worker"]
