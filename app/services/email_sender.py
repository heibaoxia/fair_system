from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class EmailSenderError(Exception):
    pass


class EmailSenderConfigurationError(EmailSenderError):
    pass


class EmailDeliveryError(EmailSenderError):
    pass


@dataclass(frozen=True)
class VerificationEmailMessage:
    recipient: str
    login_id: str
    subject: str
    text_body: str
    verification_url: str
    expires_at: datetime


@dataclass(frozen=True)
class SMTPEmailSettings:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    use_tls: bool = True
    use_ssl: bool = False
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "SMTPEmailSettings":
        use_ssl = _env_flag("FAIR_SMTP_USE_SSL", default=False)
        use_tls = _env_flag("FAIR_SMTP_USE_TLS", default=not use_ssl)
        default_port = "465" if use_ssl else "587"
        host = os.getenv("FAIR_SMTP_HOST", "").strip()
        sender = os.getenv("FAIR_EMAIL_FROM", "").strip()
        port_text = os.getenv("FAIR_SMTP_PORT", default_port).strip()

        if not host:
            raise EmailSenderConfigurationError("FAIR_SMTP_HOST is required.")
        if not sender:
            raise EmailSenderConfigurationError("FAIR_EMAIL_FROM is required.")

        try:
            port = int(port_text)
        except ValueError as exc:
            raise EmailSenderConfigurationError("FAIR_SMTP_PORT must be an integer.") from exc

        timeout_text = os.getenv("FAIR_SMTP_TIMEOUT_SECONDS", "10").strip()
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as exc:
            raise EmailSenderConfigurationError("FAIR_SMTP_TIMEOUT_SECONDS must be numeric.") from exc

        username = os.getenv("FAIR_SMTP_USERNAME")
        password = os.getenv("FAIR_SMTP_PASSWORD")
        return cls(
            host=host,
            port=port,
            sender=sender,
            username=username.strip() if username else None,
            password=password,
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout_seconds=timeout_seconds,
        )


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_verification_email_message(
    *,
    recipient: str,
    login_id: str,
    token: str,
    expires_at: datetime,
    verification_base_url: str,
) -> VerificationEmailMessage:
    base_url = verification_base_url.strip()
    if not base_url:
        raise EmailSenderConfigurationError("Verification base URL is required.")

    verification_url = _build_clickable_verification_url(base_url, token)
    subject = "Verify your FAIR account email"
    text_body = (
        f"Hello {login_id},\n\n"
        "Please verify your email address to activate your FAIR account.\n"
        f"Verification link: {verification_url}\n"
        f"This link expires at {expires_at.isoformat()}.\n"
    )
    return VerificationEmailMessage(
        recipient=recipient,
        login_id=login_id,
        subject=subject,
        text_body=text_body,
        verification_url=verification_url,
        expires_at=expires_at,
    )


def _build_clickable_verification_url(base_url: str, token: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/") or parts.path
    target_path = "/login" if path == "/auth/verify-email" else parts.path
    query_params = parse_qsl(parts.query, keep_blank_values=True)
    query_params.append(("token", token))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            target_path,
            urlencode(query_params),
            parts.fragment,
        )
    )


class SMTPEmailSender:
    def __init__(self, settings: SMTPEmailSettings):
        self.settings = settings

    @classmethod
    def from_env(cls) -> "SMTPEmailSender":
        return cls(SMTPEmailSettings.from_env())

    def send_verification_email(self, message: VerificationEmailMessage) -> None:
        email_message = EmailMessage()
        email_message["Subject"] = message.subject
        email_message["From"] = self.settings.sender
        email_message["To"] = message.recipient
        email_message.set_content(message.text_body)

        try:
            if self.settings.use_ssl:
                with smtplib.SMTP_SSL(
                    self.settings.host,
                    self.settings.port,
                    timeout=self.settings.timeout_seconds,
                ) as smtp:
                    self._login_if_needed(smtp)
                    smtp.send_message(email_message)
                return

            with smtplib.SMTP(
                self.settings.host,
                self.settings.port,
                timeout=self.settings.timeout_seconds,
            ) as smtp:
                smtp.ehlo()
                if self.settings.use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                self._login_if_needed(smtp)
                smtp.send_message(email_message)
        except OSError as exc:
            raise EmailDeliveryError("Failed to deliver verification email.") from exc

    def _login_if_needed(self, smtp: smtplib.SMTP) -> None:
        if self.settings.username:
            smtp.login(self.settings.username, self.settings.password or "")


__all__ = [
    "EmailDeliveryError",
    "EmailSenderConfigurationError",
    "EmailSenderError",
    "SMTPEmailSender",
    "SMTPEmailSettings",
    "VerificationEmailMessage",
    "build_verification_email_message",
]
