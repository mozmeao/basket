DC := 'docker compose'
DC_CI := 'bin/dc.sh'

@_default:
    just --list

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
    {{ DC }} run --rm test ./bin/check-pinned-requirements.py

# regenerate requirements *.txt files based on *.in files
@compile-requirements: _docker-pull
    {{ DC }} run --rm compile-requirements

# install Python dependencies for local development
@install-local-python-deps:
    pip install -r requirements/dev.txt

# ----------------------------
# CI (GitHub Actions) commands
# ----------------------------

@_make-docker-build-ci:
    just build-ci

# build docker images for use in our CI pipeline
@build-ci: _docker-pull
    {{ DC_CI }} build --pull web
    {{ DC_CI }} build builder
    @touch .just-docker-build-ci

# run tests against files in docker image built by CI
@test-ci: _make-docker-build-ci
    {{ DC_CI }} run test-image

# push to docker hub
@push-ci: _make-docker-build-ci
    docker/bin/push2dockerhub.sh
