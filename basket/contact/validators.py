import re

URL_PATTERN = re.compile(
    r"(https?://|www\.|\.[a-z]{2,}(?:/|\s|$))",
    re.IGNORECASE
)

def reject_urls(value: str, field_name: str) -> str:
    if URL_PATTERN.search(value):
        raise ValueError(f"{field_name} must not contain URLs or domain names")
    return value
