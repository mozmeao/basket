import uuid
from datetime import datetime

from ninja import Field, Schema
from pydantic import EmailStr, field_validator


class NewsletterSchema(Schema):
    active: bool
    description: str
    firefox_confirm: bool
    indent: bool
    is_mofo: bool
    is_waitlist: bool
    languages: list[str]
    order: int
    private: bool
    requires_double_optin: bool
    show: bool
    slug: str
    title: str
    vendor_id: str


class NewsletterModelSchema(NewsletterSchema):
    # Subclass to easily convert a `Newsletter` model object to the schema.
    #
    # This overrides the `languages` to convert from the CSV string to a list using the `Newsletter`
    # object's `language_list` property.
    languages: list[str] = Field(alias="language_list")


class RecoverUserSchema(Schema):
    # Used for the `/users/recover/` endpoint's request body validation.
    email: EmailStr


class AssignExternalIdSchema(Schema):
    # Request body for the `/users/assign/` webhook. The caller (e.g. Braze, via
    # Liquid templating) supplies these fields. At least one is required (validated in the view).
    email: EmailStr | None = None
    basket_token: str | None = Field(default=None, max_length=128)
    fxa_id: str | None = Field(default=None, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_to_none(cls, value):
        # Braze Liquid renders an empty string for absent attributes; treat that as "no email"
        # so a basket_token/fxa_id-only call isn't rejected by EmailStr validation.
        return value or None


class NewslettersSchema(Schema):
    newsletters: dict[str, NewsletterSchema]
    status: str


class UserSchema(Schema):
    country: str | None
    email: str
    first_name: str | None
    last_name: str | None
    fxa_primary_email: str | None
    has_fxa: bool = False
    lang: str | None
    mofo_relevant: bool = False
    newsletters: list[str]
    optin: bool = False
    optout: bool = False
    token: uuid.UUID
    created_date: datetime
    last_modified_date: datetime
    status: str


class ErrorSchema(Schema):
    status: str
    desc: str
    code: int


class OkSchema(Schema):
    status: str
