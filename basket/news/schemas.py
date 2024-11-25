import uuid
from datetime import datetime

from ninja import ModelSchema, Schema

from basket.news.models import Newsletter


class NewsletterSchema(ModelSchema):
    languages: list[str]

    class Meta:
        model = Newsletter
        exclude = ["id"]


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
