from django.test.utils import override_settings

from basket.base.utils import email_is_testing


@override_settings(TESTING_EMAIL_DOMAINS=["restmail.net"], USE_SANDBOX_BACKEND=False)
def test_email_is_testing():
    assert email_is_testing("dude@restmail.net")
    assert not email_is_testing("dude@restmail.net.com")
    assert not email_is_testing("dude@real.restmail.net")
    assert not email_is_testing("restmail.net@example.com")
    assert not email_is_testing("dude@example.com")
