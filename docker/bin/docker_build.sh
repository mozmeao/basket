#!/bin/bash

set -exo pipefail

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

DOCKER_NO_CACHE=false
DOCKER_PULL=false
DOCKER_CTX='.'

# parse cli args
while [[ $# -gt 1 ]]; do
    key="$1"
    case $key in
        -c|--context)
            DOCKER_CTX="$2"
            shift
            ;;
        -n|--no-cache)
            DOCKER_NO_CACHE=true
            ;;
        -p|--pull)
            DOCKER_PULL=true
            ;;
    esac
    shift # past argument or value
done

# build the docker image
docker build -t "$DOCKER_IMAGE_TAG" --pull="$DOCKER_PULL" --no-cache="$DOCKER_NO_CACHE" --build-arg "GIT_SHA=${GIT_COMMIT}" "$DOCKER_CTX"
