from django.core.mail import send_mail
from django.template.loader import render_to_string

from basket.base.decorators import rq_task


@rq_task
def send_email_confirmation(name, email, confirm_link):
    email_subject = "Verify your email: Joint Statement on AI Safety and Openness"
    email_body = render_to_string(
        "petition/confirmation_email.txt",
        {
            "name": name,
            "confirm_link": confirm_link,
        },
    )
    email_from = "Mozilla <noreply@mozilla.com>"
    email_to = [f"{name} <{email}>"]

    send_mail(email_subject, email_body, email_from, email_to)
