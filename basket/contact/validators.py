import re

import regex

URL_PATTERN = re.compile(r"(https?://|www\.|\.[a-z]{2,}(?:/|\s|$))", re.IGNORECASE)

NAME_PATTERN = regex.compile(r"^[\p{L}\s\-']+$")


def reject_urls(value: str, field_name: str) -> str:
    if URL_PATTERN.search(value):
        raise ValueError(f"{field_name} must not contain URLs or domain names")
    return value


def validate_name_shape(value: str, field_name: str) -> str:
    if not NAME_PATTERN.match(value):
        raise ValueError(f"{field_name} may only contain letters, spaces, hyphens, and apostrophes")
    return value
