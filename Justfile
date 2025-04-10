DC := 'docker compose'

@_default:
    just --list --unsorted

# format the Justfile
@fmt:
    just --fmt --unstable

# ------
# Docker
# ------

@_env:
    touch .env

@_docker-build:
    -[ -f .just-docker-build ] || just build

@_docker-pull:
    -[ -f .just-docker-pull ] || just pull

# build docker images for dev
@build: _docker-pull
    {{ DC }} build --pull web
    touch .just-docker-build

# pull the latest production images from Docker Hub
@pull: _env
    -GIT_COMMIT= {{ DC }} pull db redis web builder
    touch .just-docker-pull

# 'docker compose' up the entire system for dev
@run: _docker-pull
    {{ DC }} up web worker

# open a bash shell in a fresh container
@run-shell:
    {{ DC }} run --rm web bash

# open a bash shell in the running app
@shell:
    {{ DC }} exec web bash

# stop all docker containers
@stop:
    {{ DC }} stop

# force stop containers
@kill:
    {{ DC }} kill

# run tests against local files
@test: _docker-pull
    {{ DC }} run --rm test

# run tests against files in docker image
@test-image: _docker-build
    {{ DC }} run --rm test-image

# remove all build, test, coverage, and Python artifacts
clean:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -rf {} +
    rm -f .coverage
    rm -rf docs/_build/
    rm -f .just-*

# -------------------
# Manage dependencies
# -------------------

# identify stale Python requirements that need upgrading
@check-requirements: _docker-pull
    {{ DC }} run --rm test uv pip list --outdated

# regenerate requirements *.txt files based on *.in files
@compile-requirements: _docker-pull
    {{ DC }} run --rm test uv lock --upgrade

# install Python dependencies for local development
@install-local-python-deps:
    uv sync
