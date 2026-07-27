from abc import ABC, abstractmethod


class ContactSink(ABC):
    """Interface for contact form submission backends.

    Input dict shape (all values are str):
        first_name - given name, max 100 chars
        last_name - family name, max 100 chars
        company - organisation name, max 200 chars
        job_title - role / title, max 150 chars
        business_email - business email address, max 250 chars
        business_phone - optional, business phone number, max 255 chars
        company_size - size of company, max 255 chars
        country - business country, max 255 chars
        opt_in - static "on" value
        lead_source - static "enterprise-default-lead-submission"
        cta - action requested by user
        firefox_use_stage - ?
        deployment_size - ?
        support_needs - comma separated list of support items requested
        timeline - requested timeline for completion
        message - user provided additional information
    """

    @abstractmethod
    def submit(self, contact: dict) -> None:
        raise NotImplementedError
