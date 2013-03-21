"""This data provides an official list of newsletters and tracks
backend-specific data for working with them in the email provider.

It's used to lookup the backend-specific newsletter name from a
generic one passed by the user. This decouples the API from any
specific email provider."""
from django.core.cache import get_cache

from news.models import Newsletter


__all__ = ('clear_newsletter_cache', 'newsletter_field', 'newsletter_name',
           'newsletter_fields', 'newsletter_names')

cache = get_cache('newsletters')


def newsletter_field(name):
    """Lookup the backend-specific field for the newsletter"""
    key = "newsletter_field|%s" % name
    data = cache.get(key)
    if data is None:
        data = Newsletter.objects.get(slug=name).vendor_id
        cache.set(key, data)
    return data


def newsletter_name(field):
    """Lookup the generic name for this newsletter field"""
    key = "newsletter_name|%s" % field
    data = cache.get(key)
    if data is None:
        data = Newsletter.objects.get(vendor_id=field).slug
        cache.set(key, data)
    return data


def newsletter_names():
    """Get a list of all the available newsletters"""
    key = "newsletter_names"
    data = cache.get(key)
    if data is None:
        data = list(Newsletter.objects.all().values_list('slug',
                                                         flat=True))
        cache.set(key, data)
    return data


def newsletter_fields():
    """Get a list of all the newsletter backend-specific fields"""
    key = "newsletter_fields"
    data = cache.get(key)
    if data is None:
        data = list(Newsletter.objects.all().values_list('vendor_id',
                                                         flat=True))
        cache.set(key, data)
    return data


def clear_newsletter_cache():
    cache.clear()
