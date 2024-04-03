import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "basket.settings")
django_application = get_wsgi_application()


# Always generate https URLs.
def https_application(environ, start_response):
    environ["wsgi.url_scheme"] = "https"
    return django_application(environ, start_response)


application = https_application
