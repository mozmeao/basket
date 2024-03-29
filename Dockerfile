# BUILDER IMAGE
FROM python:3.12-slim-bookworm AS builder

# Extra python env
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PATH="/venv/bin:$PATH"

COPY docker/bin/apt-install /usr/local/bin/
RUN apt-install build-essential default-libmysqlclient-dev libxslt1.1 libxml2 libxml2-dev libxslt1-dev

RUN python -m venv /venv

WORKDIR /app
ENV DJANGO_SETTINGS_MODULE=basket.settings

# Install app
COPY requirements/* /app/requirements/

# The setuptools install is needed for pyfxa (currently v0.7.7) which calls `pkg_resources`,
# and Python 3.12 no longer adds setuptools by default to the venv.
RUN pip install -U setuptools && \
    pip install --require-hashes --no-cache-dir -r requirements/dev.txt

COPY . /app
RUN DEBUG=False SECRET_KEY=foo ALLOWED_HOSTS=localhost, DATABASE_URL=sqlite:// \
    ./manage.py collectstatic --noinput
# END BUILDER IMAGE

# FINAL IMAGE
FROM python:3.12-slim-bookworm

# Extra python env
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PATH="/venv/bin:$PATH"
EXPOSE 8000
CMD ["bin/run-prod.sh"]
WORKDIR /app
ENV DJANGO_SETTINGS_MODULE=basket.settings

COPY docker/bin/apt-install /usr/local/bin/
RUN apt-install default-libmysqlclient-dev libxslt1.1 libxml2

ARG GIT_SHA=latest
ENV GIT_SHA=${GIT_SHA}

# add non-priviledged user
RUN adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev

COPY --from=builder /venv /venv
COPY --from=builder /app /app

# Change User
RUN chown webdev.webdev -R .
USER webdev
