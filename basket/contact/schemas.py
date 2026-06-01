from ninja import Schema
from pydantic import Field, field_validator

from .validators import count_urls, reject_urls, validate_name_shape

BLOCKED_EMAIL_DOMAINS = frozenset({
    "mailinator.com",
    "tempmail.com",
    "guerrillamail.com",
    "throwaway.email",
    "10minutemail.com"
})

class ContactEnterpriseSchema(Schema):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str  = Field(..., min_length=1, max_length=100)
    email: str      = Field(..., min_length=1, max_length=255)
    company: str    = Field(..., min_length=1, max_length=200)
    job_title: str  = Field(..., min_length=1, max_length=150)
    message: str    = Field(..., min_length=1, max_length=2000)
    website: str    = Field(default="")

    @field_validator("first_name", "last_name", "company")
    @classmethod
    def no_urls(cls, v: str, info) -> str:
        return reject_urls(v, info.field_name)

    @field_validator("message")
    @classmethod
    def too_many_urls(cls, v: str, info) -> str:
        return count_urls(v, info.field_name)

    @field_validator("first_name", "last_name")
    @classmethod
    def names_contain_invalid_characters(cls, v: str, info) -> str:
        return validate_name_shape(v, info.field_name)

    @field_validator("email")
    @classmethod
    def no_spam_emails(cls, v: str, info) -> str:
        domain = v.split("@")[-1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS:
            raise ValueError("Email domain is not allowed.")
        return v
