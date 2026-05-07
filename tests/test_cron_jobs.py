"""Daily attempt counter (the autonomous-miner cost ceiling) and wrapper-script
generation. Anything that depends on Hermes' cron.jobs module is mocked out
since cron.jobs only exists inside the Hermes runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hermes_botcoin import cron_jobs as cron_lifecycle  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


def test_no_counter_yet_reads_zero():
    assert cron_lifecycle.read_today_count() == 0


def test_increment_creates_and_advances_counter():
    assert cron_lifecycle.increment_today_count() == 1
    assert cron_lifecycle.increment_today_count() == 2
    assert cron_lifecycle.increment_today_count() == 3
    assert cron_lifecycle.read_today_count() == 3


def test_daily_ceiling_default():
    os.environ.pop("BOTCOIN_MAX_ATTEMPTS_PER_DAY", None)
    assert cron_lifecycle.daily_ceiling() == 100


def test_daily_ceiling_env(monkeypatch):
    monkeypatch.setenv("BOTCOIN_MAX_ATTEMPTS_PER_DAY", "42")
    assert cron_lifecycle.daily_ceiling() == 42


def test_daily_ceiling_clamps_invalid_to_default(monkeypatch):
    monkeypatch.setenv("BOTCOIN_MAX_ATTEMPTS_PER_DAY", "not-a-number")
    assert cron_lifecycle.daily_ceiling() == 100


def test_daily_ceiling_clamps_zero_to_one(monkeypatch):
    monkeypatch.setenv("BOTCOIN_MAX_ATTEMPTS_PER_DAY", "0")
    assert cron_lifecycle.daily_ceiling() == 1


def test_counter_files_have_iso_date_naming(isolated_home):
    cron_lifecycle.increment_today_count()
    counter_dir = isolated_home / cron_lifecycle.COUNTER_DIR_NAME
    files = sorted(counter_dir.glob("attempts-*.count"))
    assert len(files) == 1
    name = files[0].name
    assert name.startswith("attempts-")
    assert name.endswith(".count")
    date = name[len("attempts-"):-len(".count")]
    assert len(date) == 10 and date[4] == "-" and date[7] == "-"


def test_wrapper_script_writes_under_hermes_home(isolated_home):
    path = cron_lifecycle._write_wrapper_script(solver="venice", model=None, force=False)
    assert path.exists()
    body = path.read_text()
    assert body.startswith("#!/usr/bin/env bash")
    assert "hermes-botcoin-mine" in body
    assert "--solver \"venice\"" in body
    assert "--max-attempts 1" in body
    assert "--quiet" in body


def test_wrapper_script_includes_model_when_given(isolated_home):
    path = cron_lifecycle._write_wrapper_script(
        solver="venice", model="zai-org-glm-5.1", force=True
    )
    body = path.read_text()
    assert '--model "zai-org-glm-5.1"' in body


def test_wrapper_script_no_overwrite_without_force(isolated_home):
    p1 = cron_lifecycle._write_wrapper_script(solver="venice", model=None)
    p1.write_text("# user customization\n")
    p2 = cron_lifecycle._write_wrapper_script(solver="anthropic", model=None, force=False)
    assert p2.read_text() == "# user customization\n"


def test_wrapper_script_overwrite_with_force(isolated_home):
    p1 = cron_lifecycle._write_wrapper_script(solver="venice", model=None)
    p1.write_text("# user customization\n")
    p2 = cron_lifecycle._write_wrapper_script(solver="anthropic", model=None, force=True)
    assert "anthropic" in p2.read_text()


def test_autostart_outside_hermes_runtime_raises_helpful_error(isolated_home, monkeypatch):
    """When cron.jobs isn't importable, autostart must surface a clear error
    pointing the user at the Hermes runtime (gateway / CLI session)."""
    # Force the lazy importer to fail by hiding any `cron` package in sys.modules.
    monkeypatch.setitem(sys.modules, "cron", None)
    with pytest.raises(RuntimeError, match="Hermes cron module unavailable"):
        cron_lifecycle.autostart(schedule="every 90s", solver="venice")
