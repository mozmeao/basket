#!/bin/bash

set -exo pipefail

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

IMAGE_TAG="mozmeao/basket:${GIT_COMMIT}"
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
    docker history -q "${IMAGE_TAG}" > /dev/null 2>&1
    return $?
}

function dockerRun() {
    env_file="$1"
    image_tag="mozorg/bedrock_${2}:${GIT_COMMIT}"
    cmd="$3"
    docker run --rm --user $(id -u) -v "$PWD:/app" --env-file "docker/envfiles/${env_file}.env" "$image_tag" bash -c "$cmd"
}

if ! imageExists; then
    docker/bin/docker_build.sh --pull
fi
