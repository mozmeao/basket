from abc import ABC, abstractmethod


class ContactSink(ABC):
    """Interface for contact form submission backends.

    Input dict shape (all values are str):
        first_name  – given name, max 100 chars
        last_name   – family name, max 100 chars
        email       – validated email address, max 255 chars
        company     – organisation name, max 200 chars
        job_title   – role / title, max 150 chars
        message     – free-text enquiry, max 2000 chars
    """

    @abstractmethod
    def submit(self, contact: dict) -> None:
        raise NotImplementedError
