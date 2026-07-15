import os
import smtplib
from email.message import EmailMessage

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


class DeliveryError(Exception):
    pass


def deliver(epub_path, settings, smtp_factory=smtplib.SMTP):
    size = os.path.getsize(epub_path)
    if size > MAX_ATTACHMENT_BYTES:
        raise DeliveryError(
            f"file is {size} bytes, over the {MAX_ATTACHMENT_BYTES}-byte "
            "Send-to-Kindle limit"
        )
    msg = EmailMessage()
    msg["From"] = settings.sender_email
    msg["To"] = settings.kindle_email
    msg["Subject"] = os.path.basename(epub_path)
    msg.set_content("Sent by acsm2kindle.")
    with open(epub_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="epub+zip",
            filename=os.path.basename(epub_path),
        )
    try:
        with smtp_factory(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise DeliveryError(f"SMTP send failed: {e}") from e
