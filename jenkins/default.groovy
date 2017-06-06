milestone()
stage ('Build Images') {
    // make sure we should continue
    env.DOCKER_REPOSITORY = 'mozmeao/basket'
    env.DOCKER_IMAGE_TAG = "${env.DOCKER_REPOSITORY}:${env.GIT_COMMIT}"
    if ( config.require_tag ) {
        try {
            sh 'docker/bin/check_if_tag.sh'
        } catch(err) {
            utils.ircNotification([stage: 'Git Tag Check', status: 'failure'])
            throw err
        }
    }
    utils.ircNotification([stage: 'Test & Deploy', status: 'starting'])
    lock ("basket-docker-${env.GIT_COMMIT}") {
        try {
            sh 'docker/bin/build_images.sh'
            sh 'docker/bin/run_tests.sh'
        } catch(err) {
            utils.ircNotification([stage: 'Docker Build', status: 'failure'])
            throw err
        }
    }
}

milestone()
stage ('Push Public Images') {
    try {
        utils.pushDockerhub()
    } catch(err) {
        utils.ircNotification([stage: 'Dockerhub Push', status: 'failure'])
        throw err
    }
}

/**
 * Do region first because deployment and testing should work like this:
 * region1:
 *   push image -> deploy app1 -> test app1 -> deploy app2 -> test app2
 * region2:
 *   push image -> deploy app1 -> test app1 -> deploy app2 -> test app2
 *
 * A failure at any step of the above should fail the entire job
 */
if ( config.apps ) {
    milestone()
    // default to usw only
    def regions = config.regions ?: ['usw']
    for (regionId in regions) {
        def region = global_config.regions[regionId]
        if ( region.db_mode == 'rw' && config.apps_rw ) {
            region_apps = config.apps + config.apps_rw
        } else {
            region_apps = config.apps
        }
        for (appname in region_apps) {
            appURL = "https://${appname}.${region.name}.moz.works"
            stageName = "Deploy ${appname}-${region.name}"
            lock (stageName) {
                milestone()
                stage (stageName) {
                    // do post deploy if this is an RW app or if there are no RW apps configured
                    if ( region.db_mode == 'rw' && config.apps_post_deploy && config.apps_post_deploy.contains(appname) ) {
                        post_deploy = 'true'
                    } else {
                        post_deploy = 'false'
                    }
                    withEnv(["DEIS_PROFILE=${region.deis_profile}",
                             "DEIS_BIN=${region.deis_bin}",
                             "RUN_POST_DEPLOY=${post_deploy}",
                             "DEIS_APPLICATION=${appname}"]) {
                        try {
                            retry(2) {
                                sh 'docker/bin/push2deis.sh'
                            }
                        } catch(err) {
                            utils.ircNotification([stage: stageName, status: 'failure'])
                            throw err
                        }
                    }
                    utils.ircNotification([message: appURL, status: 'shipped'])
                }
            }
        }
    }
}
