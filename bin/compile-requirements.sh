#!/bin/bash

set -exo pipefail

export CUSTOM_COMPILE_COMMAND="make compile-requirements"
if [[ "$1" == "--upgrade" ]]; then
    pip-compile-multi --generate-hashes prod --generate-hashes dev --upgrade
else
    pip-compile-multi --generate-hashes prod --generate-hashes dev
fi
