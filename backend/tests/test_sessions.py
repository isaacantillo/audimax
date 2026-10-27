"""Sessions remember the device and place they are used from; users see their own, the admin everyone's."""

import datetime

from app.auth import SEEN_EVERY, touch
from app.models import AuthSession
from app.routers.auth import describe_device
from app.services import geoip
from tests.conftest import login_as

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"


def test_devices_read_like_a_person_would_say_them():
    assert describe_device(IPHONE) == "Mobile Safari on iOS · iPhone"
    assert describe_device("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36") == "Chrome on Mac OS X"
    assert describe_device(None) == "Unknown device"


def test_location_of_private_and_bad_addresses():
    assert geoip.lookup("192.168.1.20") == "Local network"
    assert geoip.lookup("127.0.0.1") == "Local network"
    assert geoip.lookup("not an ip") is None
    assert geoip.lookup(None) is None


class Conn:
    def __init__(self, ip, ua):
        self.client = type("Client", (), {"host": ip})()
        self.headers = {"user-agent": ua}


def test_last_seen_is_written_at_most_every_few_minutes_unless_the_ip_changes():
    session = AuthSession()
    t0 = datetime.datetime(2026, 10, 27, 12, tzinfo=datetime.UTC)
    assert touch(session, Conn("10.0.0.1", IPHONE), t0)
    assert session.location == "Local network" and session.last_seen_at == t0
    assert not touch(session, Conn("10.0.0.1", IPHONE), t0 + SEEN_EVERY / 2)
    assert touch(session, Conn("10.0.0.2", IPHONE), t0 + SEEN_EVERY / 2), "a new IP is recorded at once"
    assert touch(session, Conn("10.0.0.2", IPHONE), t0 + SEEN_EVERY * 2)


async def test_only_the_admin_sees_or_manages_sessions(authed):
    assert (await authed.get("/api/auth/me")).json()["is_admin"] is False
    assert (await authed.get("/api/auth/sessions")).status_code == 403
    admin = await login_as(authed, "boss", admin=True)
    some_session = (await admin.get("/api/auth/sessions")).json()[0]["id"]
    user = await login_as(admin, "mallory")
    assert (await user.delete(f"/api/auth/sessions/{some_session}")).status_code == 403


async def test_admin_sees_and_revokes_everyones_sessions(authed):
    admin = await login_as(authed, "boss", admin=True)
    assert (await admin.get("/api/auth/me")).json()["is_admin"] is True
    sessions = (await admin.get("/api/auth/sessions")).json()
    assert sorted(s["username"] for s in sessions) == ["boss", "tester"]
    mine = next(s for s in sessions if s["current"])
    assert mine["username"] == "boss" and mine["location"] == "Local network"
    tester = next(s for s in sessions if s["username"] == "tester")
    assert (await admin.delete(f"/api/auth/sessions/{tester['id']}")).status_code == 204
    assert [s["username"] for s in (await admin.get("/api/auth/sessions")).json()] == ["boss"]
    assert (await admin.delete(f"/api/auth/sessions/{mine['id']}")).status_code == 204
    assert (await admin.get("/api/auth/me")).status_code == 401, "logging out your own session signs you out"
