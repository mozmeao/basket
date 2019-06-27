#!/bin/bash
# Needs DOCKER_USERNAME, DOCKER_PASSWORD, and DOCKER_REPOSITORY environment variables.
set -ex

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

DOCKER_USERNAME="${DOCKER_USERNAME:-mozjenkins}"

docker login -u $DOCKER_USERNAME -p $DOCKER_PASSWORD

# Push to docker hub
docker push $DOCKER_IMAGE_TAG

if [[ "$GIT_TAG_DATE_BASED" == true ]]; then
    # git tag
    docker tag "$DOCKER_IMAGE_TAG" "$DOCKER_REPOSITORY:$GIT_TAG"
    docker push "$DOCKER_REPOSITORY:$GIT_TAG"
    # latest
    docker tag "$DOCKER_IMAGE_TAG" "$DOCKER_REPOSITORY:latest"
    docker push "$DOCKER_REPOSITORY:latest"
    # builder latest for cache
    docker tag "$DOCKER_REPOSITORY:builder-$GIT_TAG" "$DOCKER_REPOSITORY:builder-latest"
    docker push "$DOCKER_REPOSITORY:builder-latest"
fi
