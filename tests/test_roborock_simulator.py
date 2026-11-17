"""Our Roborock connector against python-roborock's own vacuum simulator.

The real library code runs (device manager, channels, status trait, commands); only Roborock's cloud and the
vacuum's firmware are simulated, by the library itself (roborock.testing). Nothing reaches the internet.
"""
import json

import pytest

pytest.importorskip("aioresponses")
from roborock.data.v1.v1_code_mappings import RoborockStateCode  # noqa: E402
from roborock.testing import FakeRoborockCloud, V1VacuumSimulator  # noqa: E402
from roborock.testing.cloud import DEFAULT_USER_DATA  # noqa: E402

from sitewitness.connectors import roborock_vac  # noqa: E402


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    login = tmp_path / "roborock.json"
    login.write_text(json.dumps({"email": "test_user", "user": DEFAULT_USER_DATA.as_dict()}))
    monkeypatch.setattr(roborock_vac, "_SESSION", None)  # a fresh kept connection per test
    c = FakeRoborockCloud()
    sim = V1VacuumSimulator(duid="sim_s7")
    sim.status.state, sim.status.battery = RoborockStateCode.charging, 88
    c.add_device(sim)
    with c.patch_device_manager():
        yield login, sim
    s = roborock_vac._SESSION
    if s is not None:
        s.run(s.reset(), 10)
        s.loop.call_soon_threadsafe(s.loop.stop)


def test_lists_the_vacuum(cloud):
    login, _ = cloud
    vacs = roborock_vac.list_vacuums(login)
    assert [v["duid"] for v in vacs] == ["sim_s7"] and vacs[0]["model"] == "roborock.vacuum.s7"


def test_commands_are_confirmed_by_the_vacuums_own_status(cloud):
    login, sim = cloud
    v = roborock_vac.RoborockVacuum("sim_s7", (), login, wait=3, sleep=lambda s: None)
    assert v.status() == {"state": "charging", "battery": 88, "problem": None}
    for action, expected in (("start", "cleaning"), ("stop", "paused"), ("dock", "returning_home")):
        r = v.do(action)
        assert r["confirmed"] and r["state"] == expected and sim.status.state.name == expected, action


def test_a_vacuum_that_ignores_a_command_is_not_called_done(cloud):
    login, sim = cloud
    r = roborock_vac.RoborockVacuum("sim_s7", (), login, wait=0.5, sleep=lambda s: None).do("pause")
    assert not r["confirmed"]  # this simulator doesn't act out pausing: we must not claim it paused
