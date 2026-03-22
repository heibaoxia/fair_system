from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.environment import ensure_env_loaded


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
        ensure_env_loaded()
        use_ssl = _env_flag("FAIR_SMTP_USE_SSL", default=False)
        use_tls = _env_flag("FAIR_SMTP_USE_TLS", default=not use_ssl)
        default_port = "465" if use_ssl else "587"
        host = os.getenv("FAIR_SMTP_HOST", "").strip()
        sender = os.getenv("FAIR_EMAIL_FROM", "").strip()
        port_text = os.getenv("FAIR_SMTP_PORT", default_port).strip()

        if not host:
            raise EmailSenderConfigurationError("缺少 SMTP 主机配置。")
        if not sender:
            raise EmailSenderConfigurationError("缺少发件人邮箱配置。")

        try:
            port = int(port_text)
        except ValueError as exc:
            raise EmailSenderConfigurationError("SMTP 端口必须是整数。") from exc

        timeout_text = os.getenv("FAIR_SMTP_TIMEOUT_SECONDS", "10").strip()
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as exc:
            raise EmailSenderConfigurationError("SMTP 超时时间必须是数字。") from exc

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
        raise EmailSenderConfigurationError("缺少验证链接基础地址。")

    verification_url = _build_clickable_verification_url(base_url, token)
    subject = "请验证你的 Fair-System 账号邮箱"
    text_body = (
        f"{login_id}，你好：\n\n"
        "请点击下方链接完成邮箱验证，验证成功后即可登录 Fair-System。\n"
        f"验证链接：{verification_url}\n"
        f"链接过期时间：{expires_at.isoformat()}。\n"
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
            raise EmailDeliveryError("验证邮件发送失败。") from exc

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
