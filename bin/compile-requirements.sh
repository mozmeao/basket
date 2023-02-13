#!/bin/bash

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -exo pipefail

export CUSTOM_COMPILE_COMMAND="make compile-requirements"

# We need this installed, but we don't want it to live in the main requirements
# We will need to periodically review this pinning

pip install -U pip==23.0
pip install pip-tools==6.12.2

pip-compile --generate-hashes -r requirements/prod.in --resolver=backtracking
pip-compile --generate-hashes -r requirements/dev.in --resolver=backtracking
