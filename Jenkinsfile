#!groovy

@Library('github.com/mozmar/jenkins-pipeline@20170315.1')

def loadBranch(String branch) {
    // load the utility functions used below
    utils = load 'jenkins/utils.groovy'
    if ( utils.skipTheBuild() ) {
        println 'Skipping this build. CI Skip detected in commit message.'
        return
    }

    if ( fileExists("./jenkins/branches/${branch}.yml") ) {
        config = readYaml file: "./jenkins/branches/${branch}.yml"
        println "config ==> ${config}"
    } else {
        println "No config for ${branch}. Nothing to do. Good bye."
        return
    }

    // load the global config
    global_config = readYaml file: 'jenkins/global.yml'
    // defined in the Library loaded above
    setGitEnvironmentVariables()

    if ( config.pipeline && config.pipeline.script ) {
        println "Loading ./jenkins/${config.pipeline.script}.groovy"
        load "./jenkins/${config.pipeline.script}.groovy"
    } else {
        println "Loading ./jenkins/default.groovy"
        load "./jenkins/default.groovy"
    }
}

node {
    stage ('Prepare') {
        checkout scm
    }
    loadBranch(env.BRANCH_NAME)
}
