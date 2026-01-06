DC := docker compose

.DEFAULT_GOAL := help
.PHONY: help _env _docker-build _docker-pull build pull run run-shell shell stop kill test test-image clean check-requirements compile-requirements install-local-python-deps

# Default target - show available commands
help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-30s %s\n", $$1, $$2}'

# ------
# Docker
# ------

_env:
	@touch .env

_docker-build:
	@-[ -f .just-docker-build ] || $(MAKE) build

_docker-pull:
	@-[ -f .just-docker-pull ] || $(MAKE) pull

build: _docker-pull ## build docker images for dev
	@$(DC) build --pull web
	@touch .just-docker-build

pull: _env ## pull the latest production images from Docker Hub
	@-GIT_COMMIT= $(DC) pull db redis web builder
	@touch .just-docker-pull

run: _docker-pull ## 'docker compose' up the entire system for dev
	@$(DC) up web worker

run-shell: ## open a bash shell in a fresh container
	@$(DC) run --rm web bash

shell: ## open a bash shell in the running app
	@$(DC) exec web bash

stop: ## stop all docker containers
	@$(DC) stop

kill: ## force stop containers
	@$(DC) kill

test: _docker-pull ## run tests against local files
	@$(DC) run --rm test

test-image: _docker-build ## run tests against files in docker image
	@$(DC) run --rm test-image

clean: ## remove all build, test, coverage, and Python artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +
	rm -f .coverage
	rm -rf docs/_build/
	rm -f .just-*

# -------------------
# Manage dependencies
# -------------------

check-requirements: _docker-pull ## identify stale Python requirements that need upgrading
	@$(DC) run --rm test ./bin/check-pinned-requirements.py

compile-requirements: _docker-pull ## regenerate requirements *.txt files based on *.in files
	@$(DC) run --rm compile-requirements

install-local-python-deps: ## install Python dependencies for local development
	@pip install -r requirements/dev.txt
