from typing import Any

from ninja import Schema
from pydantic import EmailStr, Field, field_validator

from .validators import reject_urls, validate_name_shape

BLOCKED_EMAIL_DOMAINS = frozenset({"mailinator.com", "tempmail.com", "guerrillamail.com", "throwaway.email", "10minutemail.com"})


class ContactSchema(Schema):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    company: str = Field(..., min_length=1, max_length=200)
    job_title: str = Field(..., min_length=1, max_length=150)
    business_email: EmailStr = Field(..., min_length=1, max_length=255)
    country: str = Field(..., min_length=1, max_length=255)
    opt_in: str = Field(default="False")
    lead_source: str = Field(default="", max_length=255)
    cta: str = Field(default="", max_length=255)
    # Honeypot: real users never fill this in.
    office_fax: str = Field(default="")

    @field_validator("first_name", "last_name", "company")
    @classmethod
    def no_urls(cls, v: str, info) -> str:
        return reject_urls(v, info.field_name)

    @field_validator("first_name", "last_name")
    @classmethod
    def names_contain_invalid_characters(cls, v: str, info) -> str:
        return validate_name_shape(v, info.field_name)

    @field_validator("business_email")
    @classmethod
    def no_spam_emails(cls, v: str, info) -> str:
        domain = v.split("@")[-1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS:
            raise ValueError("Email domain is not allowed.")
        return v


class ContactBasicSchema(ContactSchema):
    accepted_terms: str = Field(..., min_length=1, max_length=255)


class ContactEnterpriseSchema(ContactSchema):
    business_phone: str = Field(default="", max_length=255)
    company_size: str = Field(default="", max_length=255)
    firefox_use_stage: str = Field(..., min_length=1, max_length=100)
    deployment_size: str = Field(..., min_length=1, max_length=100)
    support_needs: str = Field(..., min_length=1, max_length=200)
    timeline: str = Field(..., min_length=1, max_length=100)
    message: str = Field(default="", max_length=2500)


class IntakeSchema(Schema):
    form_id: str = Field(..., min_length=1, max_length=255)
    data: dict[str, Any]
    source_url: str = Field(default="", max_length=2000)
