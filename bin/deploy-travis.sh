#!/bin/bash
set -e

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

git remote add deis-$1 ssh://git@deis.us-west.moz.works:2222/basket-$1.git
git checkout -b travis-deploy-$1
git push -f deis-$1 travis-deploy-$1:master
