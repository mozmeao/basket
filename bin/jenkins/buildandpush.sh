#!/bin/bash
set -xe

# Workaround to ignore mtime until we upgrade to Docker 1.8
# See https://github.com/docker/docker/pull/12031
find . -newerat 20140101 -exec touch -t 201401010000 {} \;

DOCKER_IMAGE_TAG=$DOCKER_REPO:$GIT_COMMIT


docker build -t $DOCKER_IMAGE_TAG .
docker save $DOCKER_IMAGE_TAG  | sudo docker-squash -t $DOCKER_IMAGE_TAG | docker load
docker tag -f $DOCKER_IMAGE_TAG $PRIVATE_REGISTRY/$DOCKER_IMAGE_TAG
docker push $PRIVATE_REGISTRY/$DOCKER_IMAGE_TAG

deis login $DEIS_CONTROLLER  --username $DEIS_USERNAME --password $DEIS_PASSWORD
deis pull $DOCKER_REPO:$GIT_COMMIT -a $DOCKER_REPO
