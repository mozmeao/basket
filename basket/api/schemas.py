import uuid

from ninja import ModelSchema, Schema

from basket.news.models import Newsletter


class NewsletterSchema(ModelSchema):
    languages: list[str]

    class Meta:
        model = Newsletter
        exclude = ["id", "order"]


class NewslettersSchema(Schema):
    newsletters: dict[str, NewsletterSchema]
    status: str


class UserSchema(Schema):
    newsletters: list[str]
    amo_display_name: str | None
    amo_last_login: str | None
    amo_location: str | None
    amo_homepage: str | None
    amo_user: bool
    amo_id: str | None
    email: str
    token: uuid.UUID
    optin: bool
    id: str | None
    first_name: str | None
    last_name: str | None
    country: str
    format: str
    lang: str
    optout: bool
    reason: str | None
    email_id: uuid.UUID
    created_date: str  # "2022-03-14T21:47:32.011954+00:00"
    last_modified_date: str  # "2023-12-05T19:36:56.655122+00:00"
    fxa_id: str | None
    fxa_primary_email: str | None
    fxa_create_date: str | None
    fxa_lang: str | None
    fxa_service: str | None
    fxa_deleted: bool
    mofo_relevant: bool
    # confirmed: bool
    # pending: bool
    # master: bool
    status: str


class ErrorSchema(Schema):
    status: str
    desc: str
    code: int
