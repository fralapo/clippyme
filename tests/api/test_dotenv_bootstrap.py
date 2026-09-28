"""A setting defined only in ``.env`` reaches every backend module.

Several modules read their settings once, at import time (allowed origins,
rate-limit table size, job log length, Smart Cut and asset paths). The backend
is imported in a fresh interpreter, as uvicorn would, with a controlled
``.env`` in the working directory (``python -c`` has no ``__main__.__file__``,
so python-dotenv searches the cwd) and those variables removed from the
inherited environment.
"""
import json
import os
import subprocess
import sys

import pytest

PROBE = r"""
import json
import clippyme.api.app as app
from clippyme.api import security
from clippyme.editing import compose, smartcut, subtitles
from clippyme.jobs import job_worker
print(json.dumps({
    "allowed_origins": security.ALLOWED_ORIGINS,
    "rate_limit_max_buckets": security._RATE_STATE_MAX,
    "max_log_lines": job_worker.MAX_LOG_LINES,
    "ae_max_parallel": smartcut._AE_MAX_PARALLEL,
    "logo_path": compose.LOGO_PATH,
    "user_fonts_dir": subtitles.USER_FONTS_DIR,
    "max_concurrent_jobs": app.MAX_CONCURRENT_JOBS,
}))
"""

DOTENV = {
    "ALLOWED_ORIGINS": "http://lan-dashboard.example:5175",
    "RATE_LIMIT_MAX_BUCKETS": "123",
    "MAX_LOG_LINES": "321",
    "AE_MAX_PARALLEL": "7",
    "CLIPPYME_LOGO_PATH": "brand/logo.png",
    "CLIPPYME_USER_FONTS_DIR": "brand/fonts",
    "MAX_CONCURRENT_JOBS": "3",
}


def _import_backend(tmp_path, dotenv_text, extra_env=None):
    (tmp_path / ".env").write_text(dotenv_text, encoding="utf-8")
    (tmp_path / "fonts").mkdir(exist_ok=True)           # the /fonts static mount
    (tmp_path / "output" / "thumbnails").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in DOTENV and k != "PYTHON_DOTENV_DISABLED"}
    env.update(extra_env or {})
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def dotenv_text():
    return "".join(f"{k}={v}\n" for k, v in DOTENV.items())


def test_dotenv_reaches_settings_read_at_import(tmp_path, dotenv_text):
    got = _import_backend(tmp_path, dotenv_text)
    assert got["allowed_origins"] == ["http://lan-dashboard.example:5175"]
    assert got["rate_limit_max_buckets"] == 123
    assert got["max_log_lines"] == 321
    assert got["ae_max_parallel"] == 7
    assert got["logo_path"] == "brand/logo.png"
    assert got["user_fonts_dir"] == "brand/fonts"
    assert got["max_concurrent_jobs"] == 3


def test_process_environment_wins_over_dotenv(tmp_path, dotenv_text):
    got = _import_backend(tmp_path, dotenv_text, extra_env={
        "ALLOWED_ORIGINS": "http://from-process.example",
        "MAX_LOG_LINES": "99",
    })
    assert got["allowed_origins"] == ["http://from-process.example"]
    assert got["max_log_lines"] == 99
    assert got["rate_limit_max_buckets"] == 123       # the rest still from .env


def test_defaults_apply_when_dotenv_sets_nothing(tmp_path):
    got = _import_backend(tmp_path, "# nothing configured\n")
    assert "http://localhost:5175" in got["allowed_origins"]
    assert got["rate_limit_max_buckets"] == 10000
    assert got["max_log_lines"] == 2000
    assert got["ae_max_parallel"] == 2
    assert got["logo_path"] == os.path.join("data", "logo.png")
    assert got["max_concurrent_jobs"] == 5
