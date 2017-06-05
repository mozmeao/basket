#!/bin/bash
# Needs DOCKER_USERNAME, DOCKER_PASSWORD, DOCKER_REPOSITORY,
# FROM_DOCKER_REPOSITORY environment variables.
#
# To set them go to Job -> Configure -> Build Environment -> Inject
# passwords and Inject env variables
#
set -ex

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

DOCKER_USERNAME="${DOCKER_USERNAME:-mozjenkins}"

docker login -u $DOCKER_USERNAME -p $DOCKER_PASSWORD -e $DOCKER_USERNAME@example.com

# Push to docker hub
docker push $DOCKER_IMAGE_TAG

if [[ "$GIT_TAG_DATE_BASED" == true ]]; then
    docker tag $FROM_DOCKER_REPOSITORY:${GIT_COMMIT} $DOCKER_REPOSITORY:$GIT_TAG
    docker push $DOCKER_REPOSITORY:$GIT_TAG
    docker tag $FROM_DOCKER_REPOSITORY:${GIT_COMMIT} $DOCKER_REPOSITORY:latest
    docker push $DOCKER_REPOSITORY:latest
fi
