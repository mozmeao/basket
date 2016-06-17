"""This data provides an official list of newsletters and tracks
backend-specific data for working with them in the email provider.

It's used to lookup the backend-specific newsletter name from a
generic one passed by the user. This decouples the API from any
specific email provider."""
from django.db.models.signals import post_save
from django.db.models.signals import post_delete
from django.core.cache import cache

from news.models import Newsletter, NewsletterGroup, SMSMessage, TransactionalEmailMessage


__all__ = ('clear_newsletter_cache', 'get_sms_messages', 'newsletter_field',
           'newsletter_name', 'newsletter_fields')


CACHE_KEY = "newsletters_cache_data"
SMS_CACHE_KEY = "sms_messages_cache_data"
TRANSACTIONAL_CACHE_KEY = "transactional_messages_cache_data"
# TODO remove after initial deployment. These values should be added to
#   to the DB. This is so we don't miss any submissions.
SMS_MESSAGES = {
    'SMS_Android': 'MTo3ODow',
}


def get_transactional_message_ids():
    """
    Returns a list of transactional message IDs that basket clients send.
    """
    data = cache.get(TRANSACTIONAL_CACHE_KEY)
    if data is None:
        data = [tx.message_id for tx in TransactionalEmailMessage.objects.all()]
        cache.set(TRANSACTIONAL_CACHE_KEY, data)

    return data


def get_sms_messages():
    """
    Returns a dict for which the keys are SMS message IDs that
    basket clients will send, and the values are the message IDs
    that our SMS vendor expects.
    """
    data = cache.get(SMS_CACHE_KEY)
    if data is None:
        # TODO have this be an empty dict when SMS_MESSAGES is removed.
        data = SMS_MESSAGES.copy()
        for msg in SMSMessage.objects.all():
            data[msg.message_id] = msg.vendor_id

        cache.set(SMS_CACHE_KEY, data)

    return data


def _newsletters():
    """Returns a data structure with the data about newsletters.
    It's cached until clear_newsletter_cache() is called, so we're
    not constantly hitting the database for data that rarely changes.

    The returned data structure looks like::

        {
            'by_name': {
                'newsletter_name_1': a Newsletter object,
                'newsletter_name_2': another Newsletter object,
            },
            'by_vendor_id': {
                'NEWSLETTER_ID_1': a Newsletter object,
                'NEWSLETTER_ID_2': another Newsletter object,
            },
            'groups': {
                'group_slug': a list of newsletter slugs,
                ...
            }
        }
    """
    data = cache.get(CACHE_KEY)
    if data is None:
        data = _get_newsletters_data()
        data['groups'] = _get_newsletter_groups_data()
        cache.set(CACHE_KEY, data)

    return data


def _get_newsletter_groups_data():
    groups = NewsletterGroup.objects.filter(active=True)
    return dict((nlg.slug, nlg.newsletter_slugs()) for nlg in groups)


def _get_newsletters_data():
    by_name = {}
    by_vendor_id = {}
    inactive = []
    for nl in Newsletter.objects.all():
        by_name[nl.slug] = nl
        by_vendor_id[nl.vendor_id] = nl
        if not nl.active:
            inactive.append(nl.slug)

    return {
        'by_name': by_name,
        'by_vendor_id': by_vendor_id,
        'inactive': inactive,
    }


def newsletter_map():
    by_name = _newsletters()['by_name']
    return {name: nl.vendor_id for name, nl in by_name.iteritems()}


def newsletter_inv_map():
    return {v: k for k, v in newsletter_map().iteritems()}


def inactive_newsletter_slugs():
    return _newsletters().get('inactive', [])


def newsletter_field(name):
    """Lookup the backend-specific field (vendor ID) for the newsletter"""
    try:
        return _newsletters()['by_name'][name].vendor_id
    except KeyError:
        return None


def newsletter_name(field):
    """Lookup the generic name for this newsletter field"""
    try:
        return _newsletters()['by_vendor_id'][field].slug
    except KeyError:
        return None


def newsletter_group_newsletter_slugs(name):
    """Return the newsletter slugs associated with a group."""
    try:
        return _newsletters()['groups'][name]
    except KeyError:
        return None


def newsletter_slugs():
    """
    Get a list of all the available newsletters.
    Returns a list of their slugs.
    """
    return _newsletters()['by_name'].keys()


def newsletter_group_slugs():
    """
    Get a list of all the available newsletter groups.
    Returns a list of their slugs.
    """
    # using get() in case old format cached
    return _newsletters().get('groups', {}).keys()


def newsletter_and_group_slugs():
    """Return a list of all newsletter and group slugs."""
    return list(set(newsletter_slugs()) | set(newsletter_group_slugs()))


def newsletter_private_slugs():
    """Return a list of private newsletter ids"""
    return [nl.slug for nl in _newsletters()['by_name'].values() if nl.private]


def slug_to_vendor_id(slug):
    """Given a newsletter's slug, return its vendor_id"""
    return _newsletters()['by_name'][slug].vendor_id


def newsletter_fields():
    """Get a list of all the newsletter backend-specific fields"""
    return _newsletters()['by_vendor_id'].keys()


def newsletter_languages():
    """
    Return a set of the 2 or 5 char codes of all the languages
    supported by newsletters.
    """
    lang_set = set()
    for newsletter in _newsletters()['by_name'].values():
        lang_set |= set(newsletter.language_list)
    return lang_set


def is_supported_newsletter_language(code):
    """
    Return True if the given language code is supported by any of the
    newsletters. (Only compares first two chars; case-insensitive.)
    """
    return code[:2].lower() in [lang[:2].lower() for lang in newsletter_languages()]


def clear_newsletter_cache(*args, **kwargs):
    cache.delete(CACHE_KEY)


def clear_sms_cache(*args, **kwargs):
    cache.delete(SMS_CACHE_KEY)


post_save.connect(clear_newsletter_cache, sender=Newsletter)
post_delete.connect(clear_newsletter_cache, sender=Newsletter)
post_save.connect(clear_newsletter_cache, sender=NewsletterGroup)
post_delete.connect(clear_newsletter_cache, sender=NewsletterGroup)
post_save.connect(clear_sms_cache, sender=SMSMessage)
post_delete.connect(clear_sms_cache, sender=SMSMessage)
