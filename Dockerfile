# BUILDER IMAGE
FROM python:3.13-slim-bookworm AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=basket.settings

COPY docker/bin/apt-install /usr/local/bin/
RUN <<EOT
apt-install build-essential ca-certificates default-libmysqlclient-dev libxslt1.1 libxml2 libxml2-dev libxslt1-dev pkg-config
python -m venv /venv
EOT

WORKDIR /app

# Install Python dependencies
COPY requirements/* /app/requirements/
RUN pip install --require-hashes --no-cache-dir -r requirements/dev.txt

COPY . /app
RUN DEBUG=false SECRET_KEY=foo ALLOWED_HOSTS=localhost DATABASE_URL=sqlite:// ./manage.py collectstatic --noinput

# END BUILDER IMAGE

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
apt-install default-libmysqlclient-dev libxslt1.1 libxml2
adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev
chown webdev:webdev /app
EOT

# Switch to non-root user before copying files
USER webdev

# On Linux, the COPY command still executes as root by default, ∴ `chown`.
COPY --from=builder --chown=webdev:webdev /venv /venv
COPY --from=builder --chown=webdev:webdev /app /app
