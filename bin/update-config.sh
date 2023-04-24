#!/bin/bash -ex
# env vars: CLUSTER_NAME, CONFIG_BRANCH, CONFIG_REPO, NAMESPACE

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

pushd $(mktemp -d)
git clone --depth=1 -b ${CONFIG_BRANCH:=main} ${CONFIG_REPO:=github-mozmar-robot:mozmeao/basket-config} basket-config
cd basket-config

set -u
for CLUSTER in ${CLUSTERS}; do
    for DEPLOYMENT in {clock-,donateworker-,fxaeventsworker-,fxaworker-,web-,worker-,}deploy.yaml; do
        DEPLOYMENT_FILE=${CLUSTER:=oregon-b}/${NAMESPACE:=basket-dev}/${DEPLOYMENT}
        if [[ -f ${DEPLOYMENT_FILE} ]]; then
            sed -i -e "s|image: .*|image: ${DOCKER_IMAGE_TAG}|" ${DEPLOYMENT_FILE}
            git add ${DEPLOYMENT_FILE}
        fi
    done
done

cp ${BIN_DIR}/acceptance-tests.sh .
git add acceptance-tests.sh
git commit -m "set ${NAMESPACE} image to ${DOCKER_IMAGE_TAG} in ${CLUSTERS}" || echo "nothing new to commit"
git push
popd
