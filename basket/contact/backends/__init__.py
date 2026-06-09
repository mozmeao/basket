from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .contact_sink import ContactSink

_REGISTRY = {
    "google_sheets": "basket.contact.backends.GoogleSheetsContactSink.GoogleSheetsContactSink",
}


def get_contact_sink() -> ContactSink:
    key = settings.ENTERPRISE_CONTACT_SINK
    dotted_path = _REGISTRY.get(key)
    if dotted_path is None:
        raise ImproperlyConfigured(f"Unknown ENTERPRISE_CONTACT_SINK: {key!r}. Valid choices: {list(_REGISTRY)}")
    from django.utils.module_loading import import_string

    return import_string(dotted_path)()
