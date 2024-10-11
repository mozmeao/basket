# BUILDER IMAGE
FROM python:3.12-slim-bookworm AS builder

ENV DJANGO_SETTINGS_MODULE=basket.settings \
    PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_REQUIRE_HASHES=1 \
    UV_VERIFY_HASHES=1 \
    VIRTUAL_ENV=/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY docker/bin/apt-install /usr/local/bin/
RUN <<EOT
apt-install build-essential ca-certificates default-libmysqlclient-dev libxslt1.1 libxml2 libxml2-dev libxslt1-dev
uv venv $VIRTUAL_ENV
EOT

WORKDIR /app

# Install Python dependencies
COPY requirements/* /app/requirements/
RUN --mount=type=cache,target=/root/.cache \
    uv pip install --no-deps -r requirements/dev.txt

COPY . /app
RUN DEBUG=False SECRET_KEY=foo ALLOWED_HOSTS=localhost, DATABASE_URL=sqlite:// ./manage.py collectstatic --noinput

# END BUILDER IMAGE

# FINAL IMAGE
FROM python:3.12-slim-bookworm

# Set environment variables
ARG GIT_SHA=latest
ENV DJANGO_SETTINGS_MODULE=basket.settings \
    GIT_SHA=${GIT_SHA} \
    PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/venv

EXPOSE 8000
CMD ["bin/run-prod.sh"]

WORKDIR /app

# Install runtime dependencies and create non-root user
COPY docker/bin/apt-install /usr/local/bin/
RUN <<EOT
apt-install default-libmysqlclient-dev libxslt1.1 libxml2
adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev
chown webdev:webdev /app
EOT

# Switch to non-root user before copying files
USER webdev

# On Linux, the COPY command still executes as root by default, ∴ `chown`.
COPY --from=builder --chown=webdev:webdev /venv /venv
COPY --from=builder --chown=webdev:webdev /app /app
