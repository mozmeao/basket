from abc import ABC, abstractmethod


class ContactSink(ABC):
    """Interface for contact form submission backends.

    `contact` holds the submitting form's fields (all values are str); a form only
    sends the fields it collects.

    Fields common to every form:
        first_name - given name, max 100 chars
        last_name - family name, max 100 chars
        company - organisation name, max 200 chars
        job_title - role / title, max 150 chars
        business_email - business email address, max 255 chars
        country - business country, max 255 chars
        opt_in - optional, whether the user opted in to receive communications
        lead_source - optional, e.g. the static "enterprise-default-lead-submission"
        cta - optional, action requested by user

    Additional "basic" fields:
        accepted_terms - whether the user accepted the privacy terms

    Additional "enterprise" fields:
        business_phone - optional, business phone number, max 255 chars
        company_size - size of company, max 255 chars
        firefox_use_stage - the stage of Firefox adoption in the company
        deployment_size - how many Firefox instances will be used
        support_needs - comma separated list of support items requested
        timeline - requested timeline for completion
        message - user provided additional information
    """

    @abstractmethod
    def submit(self, contact: dict) -> None:
        raise NotImplementedError
