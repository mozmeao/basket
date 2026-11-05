# Pinned `uv` binary, copied into the stages that install Python deps
FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

# BUILDER IMAGE
FROM python:3.13-slim-bookworm AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=basket.settings \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON=3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1

COPY docker/bin/apt-install /usr/local/bin/
RUN apt-install build-essential ca-certificates default-libmysqlclient-dev libxslt1.1 libxml2 libxml2-dev libxslt1-dev pkg-config
COPY --from=uv /uv /usr/local/bin/

WORKDIR /app

# Install Python dependencies, including the dev group, which the final image also uses for tests
COPY pyproject.toml uv.lock /app/
RUN uv sync --locked

COPY . /app
RUN DEBUG=false SECRET_KEY=foo ALLOWED_HOSTS=localhost DATABASE_URL=sqlite:// ./manage.py collectstatic --noinput

# END BUILDER IMAGE

# Lockfile updates for `make compile-requirements`
#
# Kept separate from `builder`, whose `uv sync --locked` fails while
# `pyproject.toml` and `uv.lock` disagree, which is exactly when this is needed
FROM python:3.13-slim-bookworm AS uv-lock

WORKDIR /app
ENV UV_PYTHON=3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1

COPY --from=uv /uv /usr/local/bin/


# FINAL IMAGE
FROM python:3.13-slim-bookworm

# Set environment variables
ARG GIT_SHA=latest
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=basket.settings \
    GIT_SHA=${GIT_SHA}

EXPOSE 8000
CMD ["bin/run-prod.sh"]

WORKDIR /app

# Install runtime dependencies and create non-root user
COPY docker/bin/apt-install /usr/local/bin/
RUN <<EOT
apt-install ca-certificates default-libmysqlclient-dev libxslt1.1 libxml2
adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev
chown webdev:webdev /app
EOT

# Switch to non-root user before copying files
USER webdev

# On Linux, the COPY command still executes as root by default, ∴ `chown`.
COPY --from=builder --chown=webdev:webdev /venv /venv
# `make check-requirements` runs `uv pip list` in this image
COPY --from=uv /uv /usr/local/bin/
COPY --from=builder --chown=webdev:webdev /app /app
