#!/bin/bash -e

source docker/bin/set_git_env_vars.sh

# create empty file for docker-compose
touch .env

docker-compose "$@"
