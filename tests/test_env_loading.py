from pathlib import Path

from app.api import auth
from app.services.email_sender import SMTPEmailSettings
from app.environment import ensure_env_loaded


SMTP_KEYS = [
    "FAIR_AUTH_VERIFY_URL_BASE",
    "FAIR_SMTP_HOST",
    "FAIR_SMTP_PORT",
    "FAIR_EMAIL_FROM",
    "FAIR_SMTP_USERNAME",
    "FAIR_SMTP_PASSWORD",
    "FAIR_SMTP_USE_TLS",
    "FAIR_SMTP_USE_SSL",
    "FAIR_SMTP_TIMEOUT_SECONDS",
]


def clear_smtp_env(monkeypatch) -> None:
    for key in SMTP_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_env_file_auto_loads_qq_smtp_settings_and_verify_url(monkeypatch, tmp_path):
    clear_smtp_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "FAIR_AUTH_VERIFY_URL_BASE=http://127.0.0.1:8000/login",
                "FAIR_SMTP_HOST=smtp.qq.com",
                "FAIR_SMTP_PORT=465",
                "FAIR_EMAIL_FROM=test@qq.com",
                "FAIR_SMTP_USERNAME=test@qq.com",
                "FAIR_SMTP_PASSWORD=test-qq-smtp-code",
                "FAIR_SMTP_USE_TLS=false",
                "FAIR_SMTP_USE_SSL=true",
                "FAIR_SMTP_TIMEOUT_SECONDS=10",
            ]
        ),
        encoding="utf-8",
    )

    loaded_path = ensure_env_loaded(force=True)
    settings = SMTPEmailSettings.from_env()

    assert loaded_path == (tmp_path / ".env").resolve()
    assert settings.host == "smtp.qq.com"
    assert settings.port == 465
    assert settings.sender == "test@qq.com"
    assert settings.username == "test@qq.com"
    assert settings.password == "test-qq-smtp-code"
    assert settings.use_tls is False
    assert settings.use_ssl is True
    assert settings.timeout_seconds == 10.0
    assert auth.get_verification_base_url() == "http://127.0.0.1:8000/login"


def test_existing_shell_env_overrides_dotenv_values(monkeypatch, tmp_path):
    clear_smtp_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "FAIR_AUTH_VERIFY_URL_BASE=http://127.0.0.1:8000/login",
                "FAIR_SMTP_HOST=smtp.qq.com",
                "FAIR_SMTP_PORT=465",
                "FAIR_EMAIL_FROM=file@qq.com",
                "FAIR_SMTP_USERNAME=file@qq.com",
                "FAIR_SMTP_PASSWORD=file-code",
                "FAIR_SMTP_USE_TLS=false",
                "FAIR_SMTP_USE_SSL=true",
                "FAIR_SMTP_TIMEOUT_SECONDS=10",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAIR_SMTP_HOST", "smtp.override.example")
    monkeypatch.setenv("FAIR_EMAIL_FROM", "override@qq.com")

    ensure_env_loaded(force=True)
    settings = SMTPEmailSettings.from_env()

    assert settings.host == "smtp.override.example"
    assert settings.sender == "override@qq.com"
    assert settings.username == "file@qq.com"
    assert settings.password == "file-code"


def test_env_example_uses_qq_defaults():
    body = Path(".env.example").read_text(encoding="utf-8")

    assert "FAIR_SMTP_HOST=smtp.qq.com" in body
    assert "FAIR_SMTP_PORT=465" in body
    assert "FAIR_SMTP_USE_TLS=false" in body
    assert "FAIR_SMTP_USE_SSL=true" in body
