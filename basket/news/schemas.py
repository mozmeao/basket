import uuid
from datetime import datetime

from ninja import Field, Schema


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
