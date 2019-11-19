#!/bin/bash
set -ex

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

# Push to docker hub
docker-compose push web

if [[ "$GIT_BRANCH" == "prod" ]]; then
    # git tag
    docker tag "$DOCKER_IMAGE_TAG" "$DOCKER_REPOSITORY:$GIT_TAG"
    docker push "$DOCKER_REPOSITORY:$GIT_TAG"
    # latest
    docker tag "$DOCKER_IMAGE_TAG" "$DOCKER_REPOSITORY:latest"
    docker push "$DOCKER_REPOSITORY:latest"
    # builder latest for cache
    docker tag "$DOCKER_REPOSITORY:builder-$GIT_COMMIT_SHORT" "$DOCKER_REPOSITORY:builder-latest"
    docker push "$DOCKER_REPOSITORY:builder-latest"
fi
