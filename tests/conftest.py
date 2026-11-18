"""Every test gets its own empty run/ files, so tests never read or change the real ones on this Mac
(added devices, saved websites, the shared folder, the pretend lamp, people), and Groq is off unless a test turns it on.
People are the made-up sample people (Layla owner, Omar broker, Visitor)."""
import pytest

from sitewitness import devices, library, people, server, sites, understand
from sitewitness.records import SAMPLE_PEOPLE


@pytest.fixture(autouse=True)
def separate_run_files(monkeypatch, tmp_path):
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "run-devices.json")
    monkeypatch.setattr(devices, "PRETEND_FILE", tmp_path / "run-pretend-plug.json")
    monkeypatch.setattr(sites, "SITES_FILE", tmp_path / "run-sites.json")
    monkeypatch.setattr(library, "SETTINGS", tmp_path / "run-shared.json")
    monkeypatch.setattr(library, "INDEX", tmp_path / "run-search.db")
    monkeypatch.setattr(people, "FILE", tmp_path / "run-people.json")
    monkeypatch.setattr(server, "OUTBOX", tmp_path / "run-outbox")
    monkeypatch.setattr(server, "EXTRA_NAMES", set())
    people.PEOPLE.clear()
    people.PEOPLE.update({k: dict(v) for k, v in SAMPLE_PEOPLE.items()})
    monkeypatch.setattr(understand, "_cache", {})
    monkeypatch.setattr(understand, "_last_calls", [])
    monkeypatch.setattr(understand, "_working_model", [])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for k in ("SW_PLUG", "SW_PLUG_HOST", "TAPO_USERNAME", "TAPO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
