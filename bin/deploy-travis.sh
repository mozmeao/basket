#!/bin/bash
set -e

# Workaround to ignore mtime until we upgrade to Docker 1.8
# See https://github.com/docker/docker/pull/12031
find . -newerat 20140101 -exec touch -t 201401010000 {} \;

function setup_ssh_bin() {
  echo '#!/bin/sh' >> ssh-bin
  echo 'exec ssh -o StrictHostKeychecking=no -o CheckHostIP=no -o UserKnownHostsFile=/dev/null "$@"' >> ssh-bin
  chmod 740 ssh-bin
  export GIT_SSH="`pwd`/ssh-bin"
}

setup_ssh_bin

eval "$(ssh-agent -s)"
openssl aes-256-cbc -K $encrypted_83630750896a_key -iv $encrypted_83630750896a_iv -in .travis/id_rsa.enc -out .travis/id_rsa -d
chmod 600 .travis/id_rsa
ssh-add .travis/id_rsa

for region in us-west eu-west; do
    DEPLOY_BRANCH="travis-deploy-${1}-${region}"
    DEPLOY_REMOTE="deis-${1}-${region}"

    git remote add $DEPLOY_REMOTE ssh://git@deis.${region}.moz.works:2222/basket-${1}.git
    git checkout -b $DEPLOY_BRANCH
    git push -f $DEPLOY_REMOTE ${DEPLOY_BRANCH}:master
done
