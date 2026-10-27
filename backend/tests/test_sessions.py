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


async def test_users_see_and_revoke_their_own_sessions(authed):
    mine = (await authed.get("/api/auth/sessions", headers={"user-agent": IPHONE})).json()
    assert len(mine) == 1 and mine[0]["current"] and mine[0]["username"] == "tester"
    assert mine[0]["location"] == "Local network" and mine[0]["ip"]

    other = await login_as(authed, "mallory")
    theirs = (await other.get("/api/auth/sessions")).json()
    assert [s["username"] for s in theirs] == ["mallory"]
    assert (await other.delete(f"/api/auth/sessions/{mine[0]['id']}")).status_code == 404, "not someone else's"

    r = await other.delete(f"/api/auth/sessions/{theirs[0]['id']}")
    assert r.status_code == 204
    assert (await other.get("/api/auth/me")).status_code == 401, "revoking your current session logs you out"


async def test_admin_sees_and_revokes_everyones_sessions(authed):
    tester_session = (await authed.get("/api/auth/sessions")).json()[0]
    admin = await login_as(authed, "boss", admin=True)
    assert (await admin.get("/api/auth/me")).json()["is_admin"] is True
    sessions = (await admin.get("/api/auth/sessions")).json()
    assert sorted(s["username"] for s in sessions) == ["boss", "tester"]
    assert (await admin.delete(f"/api/auth/sessions/{tester_session['id']}")).status_code == 204
    assert sorted(s["username"] for s in (await admin.get("/api/auth/sessions")).json()) == ["boss"]
