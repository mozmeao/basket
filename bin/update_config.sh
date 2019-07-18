#!/bin/bash
set -ex
# env vars: CLUSTER_NAME, CONFIG_BRANCH, CONFIG_REPO, NAMESPACE

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/../docker/bin/set_git_env_vars.sh # sets DOCKER_IMAGE_TAG

pushd $(mktemp -d)
git clone --depth=1 -b ${CONFIG_BRANCH:=master} ${CONFIG_REPO:=github-mozmar-robot:mozmeao/basket-config} basket-config
cd basket-config

set -u
for DEPLOYMENT in {clock-,donateworker-,fxaeventsworker-,fxaworker-,web-,worker-,}deploy.yaml; do
    DEPLOYMENT_FILE=${CLUSTER_NAME:=oregon-b}/${NAMESPACE:=basket-dev}/${DEPLOYMENT}
    if [[ -f ${DEPLOYMENT_FILE} ]]; then
        sed -i -e "s|image: .*|image: ${DOCKER_IMAGE_TAG}|" ${DEPLOYMENT_FILE}
        git add ${DEPLOYMENT_FILE}
    fi
done

git commit -m "set image to ${DOCKER_IMAGE_TAG} in ${CLUSTER_NAME}" || echo "nothing new to commit"
git push
popd
