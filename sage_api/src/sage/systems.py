"""Registered SAP systems. Admin-only; never deleted, only disabled."""
import re

from cryptography.fernet import InvalidToken

from sage.sap.rfc import RfcError, RfcParams
from sage.sap.ssh import SshError, SshParams, fingerprint
from sage.util import iso

_PUBLIC = ("id,label,sid,description,ashost,sysnr,client,rfc_user,status,created_at,updated_at,"
           "(SELECT COUNT(*) FROM system_ssh WHERE system_id=systems.id) AS ssh_configured")
# Function modules and groups: optional /NAMESPACE/ prefix, then letters, digits and underscores; at most 30 characters.
_ABAP_NAME = re.compile(r"^(/[A-Z0-9]{1,10}/)?[A-Z][A-Z0-9_]*$")
_FIELDS = ("label", "sid", "description", "ashost", "sysnr", "client", "rfc_user")


class SystemsError(Exception):
    pass


class SystemsService:
    def __init__(self, db, box, audit, rfc):
        self._db, self._box, self._audit, self._rfc = db, box, audit, rfc

    async def get(self, system_id):
        return await self._db.fetchone(f"SELECT {_PUBLIC} FROM systems WHERE id=?", (system_id,))

    async def by_label(self, label):
        return await self._db.fetchone(f"SELECT {_PUBLIC} FROM systems WHERE label=?", (label,))

    async def list(self, only_active=False):
        sql = f"SELECT {_PUBLIC} FROM systems" + (" WHERE status='active'" if only_active else "") + " ORDER BY label"
        return await self._db.fetchall(sql)

    async def load_params(self, system_id) -> RfcParams:
        r = await self._db.fetchone("SELECT * FROM systems WHERE id=?", (system_id,))
        try:
            passwd = self._box.decrypt(r["rfc_password_enc"])
        except InvalidToken:
            # Happens when the master key volume was lost or replaced: the stored password is unreadable.
            raise RfcError("LOGIN", "The stored RFC password cannot be decrypted. Enter the RFC password again.") from None
        return RfcParams(r["ashost"], r["sysnr"], r["client"], r["rfc_user"], passwd)

    async def ssh_public(self, system_id) -> dict:
        """What the UI may see of the SSH setup: never the secret."""
        r = await self._db.fetchone("SELECT host,port,user,auth,host_key FROM system_ssh WHERE system_id=?", (system_id,))
        if not r:
            return {"configured": False}
        return {"configured": True, "host": r["host"], "port": r["port"], "user": r["user"], "auth": r["auth"],
                "trusted": bool(r["host_key"]), "fingerprint": fingerprint(r["host_key"]) if r["host_key"] else ""}

    async def load_ssh(self, system_id) -> SshParams | None:
        r = await self._db.fetchone("SELECT * FROM system_ssh WHERE system_id=?", (system_id,))
        if not r:
            return None
        try:
            secret = self._box.decrypt(r["secret_enc"])
        except InvalidToken:
            raise SshError("LOGIN", "The stored SSH secret cannot be decrypted. Enter it again.") from None
        return SshParams(r["host"], r["port"], r["user"], r["auth"], secret, r["host_key"])

    async def set_ssh(self, system_id, host, port, user, auth, secret, actor):
        """Save the optional SSH access. A new host or port drops the trusted host key: an admin must trust it again."""
        if auth == "key":
            import asyncssh
            try:
                asyncssh.import_private_key(secret)
            except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError, ValueError):
                raise SystemsError("bad_ssh_key") from None
        old = await self._db.fetchone("SELECT host,port,host_key FROM system_ssh WHERE system_id=?", (system_id,))
        keep = old["host_key"] if old and (old["host"], old["port"]) == (host, port) else ""
        await self._db.execute(
            "INSERT INTO system_ssh(system_id,host,port,user,auth,secret_enc,host_key,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(system_id) DO UPDATE SET host=excluded.host, port=excluded.port, user=excluded.user, auth=excluded.auth, "
            "secret_enc=excluded.secret_enc, host_key=excluded.host_key, updated_at=excluded.updated_at",
            (system_id, host, port, user, auth, self._box.encrypt(secret), keep, iso()))
        await self._audit.write("system.ssh", actor, detail={"system_id": system_id, "host": host, "port": port, "user": user, "auth": auth})

    async def clear_ssh(self, system_id, actor):
        await self._db.execute("DELETE FROM system_ssh WHERE system_id=?", (system_id,))
        await self._audit.write("system.ssh_clear", actor, detail={"system_id": system_id})

    async def trust_ssh_host_key(self, system_id, public_line, actor):
        await self._db.execute("UPDATE system_ssh SET host_key=?, updated_at=? WHERE system_id=?", (public_line, iso(), system_id))
        await self._audit.write("system.ssh_trust", actor, detail={"system_id": system_id, "fingerprint": fingerprint(public_line)})

    async def test(self, system_id) -> dict:
        try:
            await self._rfc.test(await self.load_params(system_id))
        except RfcError as e:
            return {"ok": False, "stage": "login" if e.code == "LOGIN" else "connect", "message": e.message}
        return {"ok": True, "stage": None, "message": ""}

    async def create(self, data: dict, actor) -> dict:
        if await self.by_label(data["label"]):
            raise SystemsError("label_taken")
        now = iso()
        sid = await self._db.execute(
            "INSERT INTO systems(label,sid,description,ashost,sysnr,client,rfc_user,rfc_password_enc,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'inactive',?,?)",
            (*(data.get(f, "") for f in _FIELDS), self._box.encrypt(data["rfc_password"]), now, now))
        await self._audit.write("system.create", actor, detail={k: data.get(k) for k in _FIELDS})
        if data.get("ssh"):
            s = data["ssh"]
            await self.set_ssh(sid, s.get("host") or data["ashost"], s["port"], s["user"], s["auth"], s["secret"], actor)
        result = await self.test(sid)
        if result["ok"]:
            await self._db.execute("UPDATE systems SET status='active', updated_at=? WHERE id=?", (iso(), sid))
        await self._audit.write("system.health_check", actor, detail={"system_id": sid, **result})
        return {**await self.get(sid), "test": result}

    async def update(self, system_id, data: dict, actor):
        sets = {k: v for k, v in data.items() if k in _FIELDS and v is not None}
        if sets:
            cols = ", ".join(f"{k}=?" for k in sets)
            await self._db.execute(f"UPDATE systems SET {cols}, updated_at=? WHERE id=?", (*sets.values(), iso(), system_id))
            self._rfc.drop(system_id)
            await self._audit.write("system.update", actor, detail={"system_id": system_id, **sets})

    async def set_credentials(self, system_id, user, password, actor):
        await self._db.execute("UPDATE systems SET rfc_user=?, rfc_password_enc=?, updated_at=? WHERE id=?",
                               (user, self._box.encrypt(password), iso(), system_id))
        self._rfc.drop(system_id)
        await self._audit.write("system.credentials", actor, detail={"system_id": system_id, "rfc_user": user})

    async def abap_names(self, system_id) -> dict[str, str]:
        rows = await self._db.fetchall("SELECT abap_object_id, name FROM abap_names WHERE system_id=?", (system_id,))
        return {r["abap_object_id"]: r["name"] for r in rows}

    async def set_abap_name(self, system_id, object_id, name, actor, known: dict[str, str]):
        """Give the object this system's own name. Using its ID again removes the override. `known` = all valid IDs."""
        name = name.strip().upper()
        if object_id not in known:
            raise SystemsError("unknown_object")
        if len(name) > 30 or not _ABAP_NAME.fullmatch(name):
            raise SystemsError("bad_abap_name")
        current = await self.abap_names(system_id)
        effective = {oid: current.get(oid, oid) for oid in known}
        effective[object_id] = name
        if len(set(effective.values())) < len(effective):
            raise SystemsError("name_in_use")
        if name == object_id:
            await self._db.execute("DELETE FROM abap_names WHERE system_id=? AND abap_object_id=?", (system_id, object_id))
        else:
            await self._db.execute(
                "INSERT INTO abap_names(system_id,abap_object_id,name,updated_by,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(system_id,abap_object_id) DO UPDATE SET name=excluded.name, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (system_id, object_id, name, actor, iso()))
        await self._audit.write("system.abap_name", actor, detail={"system_id": system_id, "abap_object_id": object_id, "name": name})

    async def set_status(self, system_id, status, actor):
        if status not in ("inactive", "active", "disabled"):
            raise SystemsError("bad_status")
        await self._db.execute("UPDATE systems SET status=?, updated_at=? WHERE id=?", (status, iso(), system_id))
        await self._audit.write("system.disable" if status == "disabled" else "system.update", actor,
                                detail={"system_id": system_id, "status": status})
