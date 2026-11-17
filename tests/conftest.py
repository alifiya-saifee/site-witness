"""Every test gets its own empty run/ files, so tests never read or change the real ones on this Mac
(added devices, saved websites, the shared folder, the pretend lamp), and Groq is off unless a test turns it on."""
import pytest

from sitewitness import devices, library, sites, understand


@pytest.fixture(autouse=True)
def separate_run_files(monkeypatch, tmp_path):
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "run-devices.json")
    monkeypatch.setattr(devices, "PRETEND_FILE", tmp_path / "run-pretend-plug.json")
    monkeypatch.setattr(sites, "SITES_FILE", tmp_path / "run-sites.json")
    monkeypatch.setattr(library, "SETTINGS", tmp_path / "run-shared.json")
    monkeypatch.setattr(library, "INDEX", tmp_path / "run-search.db")
    monkeypatch.setattr(understand, "_cache", {})
    monkeypatch.setattr(understand, "_last_calls", [])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for k in ("SW_PLUG", "SW_PLUG_HOST", "TAPO_USERNAME", "TAPO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
