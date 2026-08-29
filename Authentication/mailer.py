import asyncio
import smtplib
from email.message import EmailMessage

from .config import settings


def _send_otp_email(recipient: str, otp: str, subject: str, purpose: str):
    if not settings.smtp_host or not settings.smtp_from:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(f"Your {purpose} code is {otp}. It expires in 10 minutes.")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


async def send_verification_email(recipient: str, otp: str):
    await asyncio.to_thread(
        _send_otp_email, recipient, otp, "Verify your Veera AI account", "verification"
    )


async def send_password_reset_email(recipient: str, otp: str):
    await asyncio.to_thread(
        _send_otp_email, recipient, otp, "Reset your Veera AI password", "password reset"
    )