"""This data provides an official list of newsletters and tracks
backend-specific data for working with them in the email provider.

It's used to lookup the backend-specific newsletter name from a
generic one passed by the user. This decouples the API from any
specific email provider."""

__all__ = ('newsletter_field', 'newsletter_name', 'newsletter_fields', 'newsletter_names')

newsletters = {
    'mozilla-and-you': 'MOZILLA_AND_YOU',
    'firefox-tips': 'FIREFOX_TIPS',
    'mobile': 'ABOUT_MOBILE',
    'beta': 'FIREFOX_BETA_NEWS',
    'aurora': 'AURORA',
    'about-mozilla': 'ABOUT_MOZILLA',
    'drumbeat': 'DRUMBEAT_NEWS_GROUP',
    'addons': 'ABOUT_ADDONS',
    'hacks': 'ABOUT_HACKS',
    'labs': 'ABOUT_LABS',
    'student-reps': 'STUDENT_REPS',
    'about-standards': 'ABOUT_STANDARDS',
    # 'mobile-addon-dev': 'MOBILE_ADDON_DEV',
    'addon-dev': 'ADD_ONS',
    'join-mozilla': 'JOIN_MOZILLA',
    'mozilla-phone': 'MOZILLA_PHONE',
    'app-dev': 'APP_DEV',
    'moz-spaces': 'MOZ_SPACE',
    'affiliates': 'AFFILIATES',
    'firefox-os': 'FIREFOX_OS',
}


def newsletter_field(name):
    """Lookup the backend-specific field for the newsletter"""
    return newsletters.get(name)


def newsletter_name(field):
    """Lookup the generic name for this newsletter field"""
    for k, v in newsletters.iteritems():
        if v == field:
            return k


def newsletter_names():
    """Get a list of all the availble newsletters"""
    return newsletters.keys()


def newsletter_fields():
    """Get a list of all the newsletter backend-specific fields"""
    return newsletters.values()
