from abc import ABC, abstractmethod


class ContactSink(ABC):
    @abstractmethod
    def submit(self, contact: dict) -> None:
        return
