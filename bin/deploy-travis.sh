#!/bin/bash
set -ex

docker login -e "$DOCKER_EMAIL" -u "$DOCKER_USERNAME" -p "$DOCKER_PASSWORD"
docker push ${DOCKER_IMAGE_TAG}
docker tag -f ${DOCKER_IMAGE_TAG} ${DOCKER_REPOSITORY}:last_successful_build
docker push ${DOCKER_REPOSITORY}:last_successful_build

# Install deis client
curl -sSL http://deis.io/deis-cli/install.sh | sh

DEIS_APP=$1

for region in us-west eu-west; do
    DEIS_CONTROLLER=https://deis.${region}.moz.works
    NR_APP="${DEIS_APP}-${region}"
    ./deis login $DEIS_CONTROLLER  --username $DEIS_USERNAME --password $DEIS_PASSWORD
    ./deis pull ${DOCKER_IMAGE_TAG} -a $DEIS_APP
    curl -H "x-api-key:$NEWRELIC_API_KEY" \
         -d "deployment[app_name]=$NR_APP" \
         -d "deployment[revision]=$TRAVIS_COMMIT" \
         -d "deployment[user]=Travis" \
         https://api.newrelic.com/deployments.xml
done
