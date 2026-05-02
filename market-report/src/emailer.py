"""Send the daily report PDF via Gmail SMTP (App Password)."""

import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 465


def send_email(
    sender: str,
    app_password: str,
    recipients: list,
    subject: str,
    body: str,
    attachment_path: str = None,
) -> None:
    msg = MIMEMultipart()
    msg['From']    = sender
    msg['To']      = ', '.join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, 'rb') as f:
            part = MIMEBase('application', 'pdf')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="{Path(attachment_path).name}"',
        )
        msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, app_password)
        server.sendmail(sender, recipients, msg.as_string())

    logger.info(f"Email delivered to {recipients} — subject: {subject!r}")
