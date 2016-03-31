#!/bin/bash
set -e

echo "Logging into the Docker Hub"
docker login -e "$DOCKER_EMAIL" -u "$DOCKER_USERNAME" -p "$DOCKER_PASSWORD"
echo "Pushing ${DOCKER_IMAGE_TAG} to Docker hub"
docker push ${DOCKER_IMAGE_TAG}
docker tag -f ${DOCKER_IMAGE_TAG} ${DOCKER_REPOSITORY}:last_successful_build
echo "Tagging as last_successful_build"
docker push ${DOCKER_REPOSITORY}:last_successful_build

# Install deis client
echo "Installing Deis client"
curl -sSL http://deis.io/deis-cli/install.sh | sh

DEIS_REGIONS=( us-west eu-west )
if [[ "$1" == "prod" ]]; then
  DEIS_APPS=( $DEIS_PROD_APP $DEIS_ADMIN_APP )
else
  DEIS_APPS=( $DEIS_DEV_APP $DEIS_STAGE_APP )
fi

for region in "${DEIS_REGIONS[@]}"; do
  DEIS_CONTROLLER="https://deis.${region}.moz.works"
  echo "Logging into the Deis Controller at $DEIS_CONTROLLER"
  ./deis login "$DEIS_CONTROLLER" --username "$DEIS_USERNAME" --password "$DEIS_PASSWORD"
  for appname in "${DEIS_APPS[@]}"; do
    # skip admin app in eu-west
    if [[ "$region" == "eu-west" && "$appname" == "$DEIS_ADMIN_APP" ]]; then
      continue
    fi
    NR_APP="${appname}-${region}"
    echo "Pulling $DOCKER_IMAGE_TAG into Deis app $appname in $region"
    ./deis pull "$DOCKER_IMAGE_TAG" -a "$appname"

    echo "Pinging New Relic about the deployment of $NR_APP"
    nr_desc="CircleCI built $DOCKER_IMAGE_TAG and deployed it to Deis in $region"
    curl -H "x-api-key:$NEWRELIC_API_KEY" \
         -d "deployment[app_name]=$NR_APP" \
         -d "deployment[revision]=$CIRCLE_SHA1" \
         -d "deployment[user]=CircleCI" \
         -d "deployment[description]=$nr_desc" \
         https://api.newrelic.com/deployments.xml
  done
done
