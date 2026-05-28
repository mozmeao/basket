from ninja import Schema
from pydantic import Field, field_validator
from .validators import reject_urls


class ContactEnterpriseSchema(Schema):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str  = Field(..., min_length=1, max_length=100)
    company: str    = Field(..., min_length=1, max_length=200)
    job_title: str  = Field(..., min_length=1, max_length=150)
    message: str    = Field(..., min_length=1, max_length=2000)

    @field_validator("first_name", "last_name", "company")
    @classmethod
    def no_urls(cls, v: str, info) -> str:
        return reject_urls(v, info.field_name)
