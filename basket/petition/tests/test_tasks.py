from basket.petition.tasks import send_email_confirmation


def test_send_email_confirmation(mocker):
    mock_send_mail = mocker.patch("basket.petition.tasks.send_mail")
    assert mock_send_mail.call_count == 0

    send_email_confirmation.delay("name", "email", "http://link")

    assert mock_send_mail.call_count == 1
    assert mock_send_mail.call_args[0][0].startswith("Verify your email:")
    assert "http://link" in mock_send_mail.call_args[0][1]
    assert mock_send_mail.call_args[0][2] == "Mozilla <noreply@mozilla.com>"
    assert mock_send_mail.call_args[0][3] == ["name <email>"]
