DC_CI = bin/dc.sh
DC = docker-compose

all: help

.env:
	@touch .env

.make.pip-compile-multi.setup:
	# This is unpinned to keep this up to date every time it's used, because dependency-checkers
	# won't spot it, but updateds might introduce larger-than-expected changes
	pip install -U pip-compile-multi

.make.docker.build:
	${MAKE} build

.make.docker.pull:
	${MAKE} pull

build: .make.docker.pull
	${DC} build --pull web
	@touch .make.docker.build

pull: .env
	-GIT_COMMIT= ${DC} pull db redis web builder
	@touch .make.docker.pull

run: .make.docker.pull
	${DC} up web

run-shell:
	${DC} run --rm web bash

shell:
	${DC} exec web bash

djshell:
	${DC} exec web python manage.py shell_plus

stop:
	${DC} stop

kill:
	${DC} kill

clean:
#	python related things
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +
#	test related things
	-rm -f .coverage
#	docs files
	-rm -rf docs/_build/
#	state files
	-rm -f .make.*

lint: .make.docker.pull
	${DC} run test flake8

test: .make.docker.pull
	${DC} run --rm test

test-image: .make.docker.build
	${DC} run --rm test-image

compile-requirements: .make.pip-compile-multi.setup
	./bin/compile-requirements.sh

upgrade-requirements: .make.pip-compile-multi.setup
	./bin/compile-requirements.sh --upgrade

docs: .make.docker.pull
	${DC} run --rm web make -C docs/ clean html

###############
# For use in CI
###############
.make.docker.build.ci:
	${MAKE} build-ci

build-ci: .make.docker.pull
	${DC_CI} build --pull web
#	tag intermediate images using cache
	${DC_CI} build builder
	@touch .make.docker.build.ci

test-ci: .make.docker.build.ci
	${DC_CI} run test-image

push-ci: .make.docker.build.ci
	docker/bin/push2dockerhub.sh

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  run                  - docker-compose up the entire system for dev"
	@echo "  build                - build docker images for dev"
	@echo "  pull                 - pull the latest production images from Docker Hub"
	@echo "  run-shell            - open a bash shell in a fresh container"
	@echo "  compile-requirements - compile requirements.in to requirements.txt"
	@echo "  shell                - open a bash shell in the running app"
	@echo "  djshell              - start the Django Python shell in the running app"
	@echo "  clean                - remove all build, test, coverage and Python artifacts"
	@echo "  lint                 - check style with flake8, jshint, and stylelint"
	@echo "  test                 - run tests against local files"
	@echo "  test-image           - run tests against files in docker image"
	@echo "  docs                 - generate Sphinx HTML documentation"
	@echo "  build-ci             - build docker images for use in our CI pipeline"
	@echo "  test-ci              - run tests against files in docker image built by CI"

.PHONY: all clean build pull docs lint run run-shell shell test test-image build-ci test-ci push-ci djshell stop kill compile-requirements upgrade-requirements
