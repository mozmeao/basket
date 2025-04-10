# BUILDER IMAGE
FROM python:3.12-slim-bookworm AS builder

# Set environment variables
ENV DJANGO_SETTINGS_MODULE=basket.settings \
    PATH="/venv/bin:$PATH"  \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/app/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    UV_FROZEN=1 \
    UV_LINK_MODE=copy \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_REQUIRE_HASHES=1 \
    UV_VERIFY_HASHES=1 \
    VIRTUAL_ENV=/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY docker/bin/apt-install /usr/local/bin/
RUN <<EOT
apt-install \
  build-essential \
  ca-certificates \
  default-libmysqlclient-dev \
  libxslt1.1 \
  libxml2 \
  libxml2-dev \
  libxslt1-dev \
  pkg-config
EOT

WORKDIR /app

# Install Python dependencies
RUN uv venv $VIRTUAL_ENV
RUN --mount=type=cache,target=/app/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project --no-editable

COPY . /app
RUN DEBUG=false SECRET_KEY=foo ALLOWED_HOSTS=localhost DATABASE_URL=sqlite:// ./manage.py collectstatic --noinput

# END BUILDER IMAGE

# FINAL IMAGE
FROM python:3.12-slim-bookworm

# Set environment variables
ARG GIT_SHA=latest
ENV DJANGO_SETTINGS_MODULE=basket.settings \
    PATH="/venv/bin:$PATH"  \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/app/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    UV_FROZEN=1 \
    UV_LINK_MODE=copy \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_REQUIRE_HASHES=1 \
    UV_VERIFY_HASHES=1 \
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
COPY --link --from=builder --chown=webdev:webdev /venv /venv
COPY --link --from=builder --chown=webdev:webdev /app /app
