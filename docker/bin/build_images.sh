#!/bin/bash

set -exo pipefail

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

DOCKER_REBUILD=false

# parse cli args
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -r|--rebuild)
            DOCKER_REBUILD=true
            ;;
    esac
    shift # past argument or value
done

function imageExists() {
    docker history -q "${DOCKER_IMAGE_TAG}" > /dev/null 2>&1
    return $?
}

if ! imageExists; then
    docker/bin/docker_build.sh --pull
fi
