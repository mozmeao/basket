#!/bin/bash

set -exo pipefail

export CUSTOM_COMPILE_COMMAND="make compile-requirements"
if [[ "$1" == "--upgrade" ]]; then
    pip-compile --generate-hashes --reuse-hashes --upgrade --upgrade-package 'django<2.3' requirements.in
else
    pip-compile --generate-hashes --reuse-hashes requirements.in
fi
