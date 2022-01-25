#!/bin/bash

set -exo pipefail

export CUSTOM_COMPILE_COMMAND="make compile-requirements"

# We need this installed, but we don't want it to live in the main requirements
# We will need to periodically review this pinning
pip install --upgrade pip-tools==6.4.0  # needs at least this version to build
pip install pip-compile-multi


if [[ "$1" == "--upgrade" ]]; then
    pip-compile-multi --generate-hashes prod --generate-hashes dev --upgrade
else
    pip-compile-multi --generate-hashes prod --generate-hashes dev
fi
