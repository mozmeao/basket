#!/bin/bash

set -exo pipefail

export CUSTOM_COMPILE_COMMAND="make compile-requirements"
pip-compile --generate-hashes --reuse-hashes requirements.in
