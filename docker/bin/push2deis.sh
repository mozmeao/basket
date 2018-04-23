#!/bin/bash
# Needs DEIS_PROFILE, DEIS_APPLICATION, NEWRELIC_API_KEY and
# NEWRELIC_APP_NAME environment variables.
#
# To set them go to Job -> Configure -> Build Environment -> Inject
# passwords and Inject env variables
#

set -ex

BIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $BIN_DIR/set_git_env_vars.sh

DEIS_BIN="${DEIS_BIN:-deis2}"
NR_APP="${DEIS_APPLICATION}-${REGION_NAME}"
NR_DESC="Jenkins built $DOCKER_IMAGE_TAG from $GIT_COMMIT_SHORT and deployed it as Deis app $DEIS_APPLICATION in $REGION_NAME"

$DEIS_BIN pull "$DOCKER_IMAGE_TAG" -a $DEIS_APPLICATION

if [[ -n "$NEWRELIC_API_KEY" ]]; then
    echo "Pinging NewRelic about the deployment of $NR_APP"
    curl -H "x-api-key:$NEWRELIC_API_KEY" \
         -d "deployment[app_name]=$NR_APP" \
         -d "deployment[revision]=$GIT_COMMIT" \
         -d "deployment[user]=MEAO Jenkins" \
         -d "deployment[description]=$NR_DESC" \
         https://api.newrelic.com/deployments.xml
fi

if [[ -n "$DATADOG_API_KEY" ]]; then
    echo "Pinging DataDog about the deployment of $NR_APP"
    dd_data=$(cat << EOF
    {
        "title": "Deployment of $NR_APP",
        "text": "$NR_DESC",
        "tags": ["region:$REGION_NAME", "appname:$DEIS_APPLICATION"],
        "aggregation_key": "$NR_APP",
        "source_type_name": "deployment",
        "alert_type": "info"
    }
EOF
    )
    curl -H "Content-type: application/json" -d "$dd_data" \
         "https://app.datadoghq.com/api/v1/events?api_key=$DATADOG_API_KEY" > /dev/null 2>&1
fi

if [[ "$RUN_POST_DEPLOY" == 'true' ]]; then
    $DEIS_BIN run -a "$DEIS_APPLICATION" -- bin/post-deploy.sh
fi
