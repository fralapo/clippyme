"""Windows has no system time zone database: zoneinfo needs the tzdata package
there, or the API rejects "Europe/Rome" and every Zernio publish fails. CI
runs on Linux only, so pin the declaration itself for both install paths."""
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parents[2]
WINDOWS = {"sys_platform": "win32", "platform_system": "Windows"}
LINUX = {"sys_platform": "linux", "platform_system": "Linux"}


def _tzdata(lines):
    reqs = [Requirement(line) for line in lines]
    return next(req for req in reqs if req.name == "tzdata")


def _requirements_txt():
    text = (REPO / "requirements.txt").read_text(encoding="utf-8")
    return [line.split(" #")[0].strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def _host_tests_extra():
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]["host-tests"]


def test_tzdata_is_installed_on_windows_only():
    for source in (_requirements_txt(), _host_tests_extra()):
        req = _tzdata(source)
        assert req.marker.evaluate(WINDOWS)
        assert not req.marker.evaluate(LINUX)


def test_runtime_and_host_tests_declare_the_same_tzdata():
    assert str(_tzdata(_requirements_txt())) == str(_tzdata(_host_tests_extra()))
