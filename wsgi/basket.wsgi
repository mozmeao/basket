import os
import site
from datetime import datetime

try:
    import newrelic.agent
except ImportError:
    newrelic = False


if newrelic:
    newrelic_ini = os.getenv('NEWRELIC_PYTHON_INI_FILE', False)
    if newrelic_ini:
        newrelic.agent.initialize(newrelic_ini)
    else:
        newrelic = False

# Remember when mod_wsgi loaded this file so we can track it in nagios.
wsgi_loaded = datetime.now()

# Add the zamboni dir to the python path so we can import manage.
wsgidir = os.path.dirname(__file__)
site.addsitedir(os.path.abspath(os.path.join(wsgidir, '../')))

# manage adds /apps, /lib, and /vendor to the Python path.
import manage

import django.conf
import django.core.handlers.wsgi
import django.core.management
import django.utils

import djcelery
djcelery.setup_loader()

# Do validate and activate translations like using `./manage.py runserver`.
# http://blog.dscpl.com.au/2010/03/improved-wsgi-script-for-use-with.html
utility = django.core.management.ManagementUtility()
command = utility.fetch_command('runserver')
command.validate()

# This is what mod_wsgi runs.
django_app = django.core.handlers.wsgi.WSGIHandler()

def application(env, start_response):
    env['wsgi.loaded'] = wsgi_loaded
    return django_app(env, start_response)

if newrelic:
    application = newrelic.agent.wsgi_application()(application)

# Uncomment this to figure out what's going on with the mod_wsgi environment.
# def application(env, start_response):
#     start_response('200 OK', [('Content-Type', 'text/plain')])
#     return '\n'.join('%r: %r' % item for item in sorted(env.items()))

# vim: ft=python
