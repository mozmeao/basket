from abc import ABC, abstractmethod


class ContactSink(ABC):
    """Interface for contact form submission backends.

    Input dict shape (all values are str):
        first_name - given name, max 100 chars
        last_name - family name, max 100 chars
        company - organisation name, max 200 chars
        job_title - role / title, max 150 chars
        business_email - business email address, max 250 chars
        business_phone - business phone number, max 255 chars
        company_size - size of company, nax 255 chars
        country - business country, max 255 chars
        opt_in
    """

    @abstractmethod
    def submit(self, contact: dict) -> None:
        raise NotImplementedError
