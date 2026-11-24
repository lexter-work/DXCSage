"""Registered SAP systems. Admin-only; never deleted, only disabled."""
from cryptography.fernet import InvalidToken

from sage.sap.rfc import RfcError, RfcParams
from sage.util import iso

_PUBLIC = "id,label,sid,description,ashost,sysnr,client,rfc_user,status,created_at,updated_at"
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

    async def set_status(self, system_id, status, actor):
        if status not in ("inactive", "active", "disabled"):
            raise SystemsError("bad_status")
        await self._db.execute("UPDATE systems SET status=?, updated_at=? WHERE id=?", (status, iso(), system_id))
        await self._audit.write("system.disable" if status == "disabled" else "system.update", actor,
                                detail={"system_id": system_id, "status": status})
