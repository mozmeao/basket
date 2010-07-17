"""SMTP email backend class."""

from django.core.mail.backends import smtp


class EmailBackend(smtp.EmailBackend):
    """
    A wrapper that manages the SMTP network connection.
    """

    def send_messages(self, email_messages):
        """
        Sends one or more EmailMessage objects and returns a tuple of
        (successful messages, failed messages).
        """
        if not email_messages:
            return
        self._lock.acquire()
        success, failed = [], []
        try:
            new_conn_created = self.open()
            if not self.connection:
                # We failed silently on open().
                # Trying to send would be pointless.
                return [], email_messages
            for message in email_messages:
                sent = self._send(message)
                if sent:
                    success.append(message)
                else:
                    failed.append(message)
            if new_conn_created:
                self.close()
        finally:
            self._lock.release()
        return success, failed
