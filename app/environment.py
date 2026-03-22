from __future__ import annotations

import os
from pathlib import Path

_LAST_LOADED_ENV_PATH: Path | None = None


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _find_dotenv(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_env_file(env_path: Path) -> None:
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_optional_quotes(value.strip())


def ensure_env_loaded(*, dotenv_path: str | Path | None = None, force: bool = False) -> Path | None:
    global _LAST_LOADED_ENV_PATH

    env_path = (
        Path(dotenv_path).expanduser().resolve()
        if dotenv_path is not None
        else _find_dotenv()
    )
    if env_path is None:
        if force:
            _LAST_LOADED_ENV_PATH = None
        return None

    resolved_path = env_path.resolve()
    if not force and _LAST_LOADED_ENV_PATH == resolved_path:
        return _LAST_LOADED_ENV_PATH

    _load_env_file(resolved_path)
    _LAST_LOADED_ENV_PATH = resolved_path
    return _LAST_LOADED_ENV_PATH
