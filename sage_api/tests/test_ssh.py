import pytest
from pydantic import BaseModel

from sage.sap.requirements import FileReadable, SshLogin
from sage.sap.ssh import SshError, fingerprint
from sage.workflows.base import SystemInput, Workflow
from tests.conftest import login_admin
from tests.test_health_setup import SYS, prepare_ok


class Empty(BaseModel):
    pass


class NeedsSsh(Workflow):
    name, description, Input, Output = "needs_ssh", "x", SystemInput, Empty
    extra_requirements = (SshLogin(), FileReadable("/usr/sap/{SID}/SUM/abap/doc/SUMOBSERVER.XML"))

    async def run(self, ctx, data):
        return Empty()


@pytest.fixture
def app_kwargs():
    return {"workflows": {"needs_ssh": NeedsSsh}}


SSH = {"host": "", "port": 22, "user": "sumadm", "auth": "password", "secret": "ssh-pass-1"}


async def mk(client, ssh=SSH):
    await login_admin(client)
    r = await client.post("/api/systems", json={**SYS, "ssh": ssh} if ssh else SYS)
    assert r.status_code == 200, r.text
    return r.json()


async def test_registration_with_ssh_is_optional_and_never_returns_the_secret(client, app):
    plain = await mk(client, None)
    assert plain["ssh_configured"] == 0 and (await client.get("/api/systems/1/ssh")).json() == {"configured": False}
    r = await client.post("/api/systems", json={**SYS, "label": "TS4", "ssh": SSH})
    sys2 = r.json()["id"]
    pub = (await client.get(f"/api/systems/{sys2}/ssh")).json()
    assert pub == {"configured": True, "host": "h", "port": 22, "user": "sumadm", "auth": "password", "trusted": False, "fingerprint": ""}
    assert "ssh-pass-1" not in str(await client.get("/api/systems")) + str(pub)
    row = await app.state.services.db.fetchone("SELECT secret_enc FROM system_ssh WHERE system_id=?", (sys2,))
    assert "ssh-pass-1" not in row["secret_enc"]


async def test_host_key_must_be_trusted_by_fingerprint_before_login(client, fake_ssh):
    await mk(client)
    t = (await client.post("/api/systems/1/ssh/test")).json()
    assert t["stage"] == "host_key" and t["needs_trust"] and t["fingerprint"] == fingerprint(fake_ssh.host_key_line)
    assert (await client.post("/api/systems/1/ssh/trust", json={"fingerprint": "SHA256:wrong"})).status_code == 409
    assert (await client.post("/api/systems/1/ssh/trust", json={"fingerprint": t["fingerprint"]})).json()["trusted"] is True
    assert (await client.post("/api/systems/1/ssh/test")).json()["ok"] is True
    assert fake_ssh.commands == ["true"]                                  # no login before the key was trusted


async def test_wrong_secret_changed_key_and_host_change(client, fake_ssh):
    import asyncssh
    await mk(client)
    fp = (await client.post("/api/systems/1/ssh/test")).json()["fingerprint"]
    await client.post("/api/systems/1/ssh/trust", json={"fingerprint": fp})
    await client.put("/api/systems/1/ssh", json={**SSH, "secret": "wrong"})
    assert (await client.post("/api/systems/1/ssh/test")).json()["stage"] == "login"
    await client.put("/api/systems/1/ssh", json=SSH)
    fake_ssh.host_key_line = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    assert (await client.post("/api/systems/1/ssh/test")).json()["changed"] is True
    await client.put("/api/systems/1/ssh", json={**SSH, "host": "other.example.com"})                # new host: trust is dropped
    assert (await client.get("/api/systems/1/ssh")).json()["trusted"] is False
    assert (await client.put("/api/systems/1/ssh", json={**SSH, "auth": "key", "secret": "not a key"})).status_code == 400
    assert (await client.delete("/api/systems/1/ssh")).json() == {"ok": True} and (await client.get("/api/systems/1/ssh")).json() == {"configured": False}


async def test_read_file_validates_paths_and_reports_errors(client, app, fake_ssh):
    await mk(client)
    fp = (await client.post("/api/systems/1/ssh/test")).json()["fingerprint"]
    await client.post("/api/systems/1/ssh/trust", json={"fingerprint": fp})
    ssh = app.state.services.ssh
    fake_ssh.files["/var/log/a.log"] = "l1\nl2\nl3"
    assert await ssh.read_file(1, "/var/log/a.log", tail_lines=2) == "l2\nl3"
    for bad in ("relative.log", "/var/log/../etc/passwd", "/a b", "/x;rm -rf /"):
        with pytest.raises(SshError) as e:
            await ssh.read_file(1, bad)
        assert e.value.code == "BAD_PATH"
    with pytest.raises(SshError) as e:
        await ssh.read_file(1, "/var/log/missing.log")
    assert e.value.code == "READ"


async def test_health_checks_ssh_and_file_requirements(client, app, fake_ssh, fake_rfc):
    prepare_ok(fake_rfc)
    await mk(client, None)
    await client.put("/api/workflows/needs_ssh/systems/1", json={"settings": {}})
    st = lambda rows: {r["req_kind"]: r["status"] for r in rows}  # noqa: E731
    rows = (await client.post("/api/workflows/needs_ssh/systems/1/check")).json()
    assert st(rows)["ssh_login"] == "fail" and st(rows)["file_readable"] == "blocked"                # no SSH set up
    await client.put("/api/systems/1/ssh", json=SSH)
    fp = (await client.post("/api/systems/1/ssh/test")).json()["fingerprint"]
    await client.post("/api/systems/1/ssh/trust", json={"fingerprint": fp})
    assert st((await client.post("/api/workflows/needs_ssh/systems/1/check")).json())["file_readable"] == "fail"   # file missing
    fake_ssh.files["/usr/sap/TS3/SUM/abap/doc/SUMOBSERVER.XML"] = "<x/>"
    rows = (await client.post("/api/workflows/needs_ssh/systems/1/check")).json()
    assert st(rows)["ssh_login"] == "pass" and st(rows)["file_readable"] == "pass"
