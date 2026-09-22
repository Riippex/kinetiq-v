"""Fifth Codex adversarial-review pass: production must never silently
start with a publicly known or trivially weak Django signing secret.

`settings.py` computes SECRET_KEY at module import time, so the only way to
prove "starting the app fails" (rather than just "a function returns an
error") is to actually import it in a fresh process with a controlled
environment -- these tests run `django.setup()` in a subprocess for that
reason.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC = str(BACKEND_ROOT / "src")


def _run_settings_import(overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env["DJANGO_SETTINGS_MODULE"] = "kinetiq.bootstrap.settings"
    for key in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG"):
        env.pop(key, None)
    # The repository's own local-dev `.env` sets DJANGO_DEBUG=true; pin it
    # false by default so these "production" cases are not silently masked
    # by `load_dotenv()` picking that up inside the subprocess. `python-dotenv`
    # never overrides a variable already present in the environment, so this
    # value wins regardless of what `.env` says.
    env["DJANGO_DEBUG"] = "false"
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_production_settings_refuse_to_start_without_a_secret_key() -> None:
    result = _run_settings_import({})

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is required" in result.stderr


def test_production_settings_refuse_the_known_placeholder_secret() -> None:
    result = _run_settings_import({"DJANGO_SECRET_KEY": "unsafe-local-development-key"})

    assert result.returncode != 0
    assert "known local-development placeholder" in result.stderr


def test_production_settings_refuse_a_trivially_short_secret() -> None:
    result = _run_settings_import({"DJANGO_SECRET_KEY": "short"})

    assert result.returncode != 0
    assert "trivially weak" in result.stderr


def test_production_settings_start_with_a_real_secret_key() -> None:
    result = _run_settings_import(
        {"DJANGO_SECRET_KEY": "a-real-secret-that-is-long-enough-for-production-use"}
    )

    assert result.returncode == 0, result.stderr


def test_debug_mode_still_falls_back_for_local_development() -> None:
    """DJANGO_DEBUG=true is the explicit opt-in for the insecure fallback --
    unset DJANGO_SECRET_KEY there must still start (never in production)."""
    result = _run_settings_import({"DJANGO_DEBUG": "true"})

    assert result.returncode == 0, result.stderr


def test_debug_mode_honors_an_explicit_secret_key_too() -> None:
    result = _run_settings_import(
        {"DJANGO_DEBUG": "true", "DJANGO_SECRET_KEY": "a-real-secret-set-even-in-debug-mode"}
    )

    assert result.returncode == 0, result.stderr
