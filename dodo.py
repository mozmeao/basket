from datetime import timedelta
from os.path import exists

from doit.tools import result_dep, timeout, LongRunning


DOIT_CONFIG = {
    'default_tasks': ['up'],
    'verbosity': 2,
}
ENV_FILE = '.env'


def task_git_revision():
    """Return the current git revision"""
    return {
        'actions': ['git rev-parse HEAD'],
    }


def task_env():
    """Setup the .env file for the first time"""
    return {
        'actions': ['cp env-dist ' + ENV_FILE],
        'uptodate': [exists(ENV_FILE)],
    }


def task_pull():
    """Pull the latest published docker images"""
    return {
        'actions': ['GIT_COMMIT= docker-compose pull web'],
        'setup': ['env'],
        'uptodate': [timeout(timedelta(days=1))],
    }


def get_build_task(ci=False):
    if ci:
        uptodate = [result_dep('git_revision')]
        cmd = 'bin/dc.sh'
    else:
        uptodate = None,
        cmd = 'docker-compose'

    return {
        'actions': ['{} build --pull web builder'.format(cmd)],
        'uptodate': uptodate,
        'file_dep': [
            'Dockerfile',
            'requirements/base.txt',
            'requirements/dev.txt',
            'requirements/prod.txt',
        ],
        'setup': ['pull'],
    }


def task_build():
    """Build the docker images"""
    return get_build_task()


def task_build_ci():
    """Build the docker images for CI"""
    return get_build_task(ci=True)


def task_up():
    """Run the local development server"""
    return {
        'actions': [LongRunning('GIT_COMMIT= docker-compose up web')],
        'setup': ['build'],
        'teardown': ['GIT_COMMIT= docker-compose stop']
    }


def task_stop():
    """Stop the local development server docker containers"""
    return {
        'actions': ['GIT_COMMIT= docker-compose stop'],
        'setup': ['env'],
    }


def task_test():
    """Run the test on local changes to basket's code"""
    return {
        'actions': ['GIT_COMMIT= docker-compose run test-local'],
        'setup': ['build'],
    }


def task_test_ci():
    """Run the test on the code baked into the image"""
    return {
        'actions': ['bin/dc.sh run test-image'],
        'setup': ['build_ci'],
    }
