/**
 * Define utility functions.
 */

/**
 * Send a notice to #www on irc.mozilla.org with the build result
 *
 * @param stage step of build/deploy
 * @param result outcome of build (will be uppercased)
*/
def ircNotification(Map args) {
    def command = "bin/irc-notify.sh"
    for (arg in args) {
        command += " --${arg.key} '${arg.value}'"
    }
    sh command
}

def pushDockerhub() {
    withCredentials([[$class: 'StringBinding',
                      credentialsId: 'DOCKER_PASSWORD',
                      variable: 'DOCKER_PASSWORD']]) {
        retry(2) {
            sh 'docker/bin/push2dockerhub.sh'
        }
    }
}

/**
 * Return True if the build should be skipped because
 * the string "[ci skip]" appears in the HEAD commit message.
 */
def skipTheBuild() {
    def output = sh([script: 'git --no-pager show -s --format=%B', returnStdout: true])
    return output.contains('[ci skip]') || output.contains('[skip ci]')
}

return this;
