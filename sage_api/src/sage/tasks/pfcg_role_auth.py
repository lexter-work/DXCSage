"""Writes to PFCG roles through the custom function modules. All tasks WRITE to SAP and are never re-run after an interrupted attempt."""
from pydantic import BaseModel

from sage.sap.requirements import DeclaredAuth, FmAuthorized, FmExists
from sage.sap.rfc import RfcError
from sage.tasks.base import Task

CHANGE_FM, TCODE_FM, DERIVED_FM, GROUP = "ZFM_RR_ROLE_AUTH_CHANGE", "ZFM_RR_TCODE_REMOVE", "ZFM_RR_DERIVED_REGENERATE", "ZFG_MCPARCHPH"
# Usual values for editing roles and generating profiles. Not verified on a system: confirm with the security team.
PFCG_AUTH = DeclaredAuth(key="role maintenance", rows=(
    ("S_USER_AGR", "ACTVT", "02"), ("S_USER_AGR", "ACT_GROUP", "*"), ("S_USER_PRO", "ACTVT", "02"), ("S_USER_PRO", "PROFILE", "*")),
    guide="Needed to change roles and generate their profiles. The security team may scope S_USER_AGR to role names.")


def _guide(fm, text):
    return f"Create {fm} in SE37 (function group {GROUP}, remote-enabled) as in the attached source. {text}"


class Value(BaseModel):
    object: str
    field: str
    low: str
    high: str = ""


class RoleChangeIn(BaseModel):
    role: str
    adds: list[Value] = []
    deletes: list[Value] = []


class Done(BaseModel):
    role: str
    success: bool
    message: str


class ChangeRoleAuth(Task):
    name, Input, Output, idempotent = "pfcg.change_role_auth", RoleChangeIn, Done, False
    requirements = (FmExists(CHANGE_FM, source="ZFM_RR_ROLE_AUTH_CHANGE.txt",
                             guide=_guide(CHANGE_FM, "Create the structure ZROLE_AUTH_VALUE first. Test it in a sandbox client before any other system.")),
                    FmAuthorized(CHANGE_FM, group=GROUP), PFCG_AUTH)

    async def run(self, ctx, data):
        rows = lambda vs: [{"OBJECT": v.object, "FIELD": v.field, "LOW": v.low, "HIGH": v.high} for v in vs]  # noqa: E731
        try:
            res = await ctx.rfc.call(ctx.system_id, CHANGE_FM, ACTIVITY_GROUP=data.role,
                                     AUTHORIZATION_VALUES=rows(data.adds), AUTHORIZATION_VALUES_DELETE=rows(data.deletes))
        except RfcError as e:         # the function module raises classic exceptions (VALUE_NOT_FOUND, ROLE_LOCKED ...): nothing was changed, except PROFILE_GENERATION_FAILED
            stale = "PROFILE_GENERATION_FAILED" in f"{e.code} {e.message}"
            return Done(role=data.role, success=False, message=f"{e.code}: {e.message}" + (" The role WAS changed but its profile is stale: regenerate it in PFCG." if stale else " The role was not changed."))
        msgs = "; ".join(str(m.get("MESSAGE", "")).strip() for m in res.get("RETURN") or [] if m.get("MESSAGE"))
        return Done(role=data.role, success=True, message=f"Changed {data.role}: {len(data.deletes)} removed, {len(data.adds)} added." + (f" {msgs}" if msgs else ""))


class TcodeIn(BaseModel):
    role: str
    tcode: str


class TcodeOut(BaseModel):
    role: str
    tcode: str
    success: bool
    return_type: str
    message: str
    removed_values: int = 0


def _ret(res) -> str:
    return "; ".join(str(m.get("MESSAGE", "")).strip() for m in res.get("ET_RETURN") or [] if m.get("MESSAGE"))


class RemoveTcode(Task):
    name, Input, Output, idempotent = "pfcg.remove_tcode", TcodeIn, TcodeOut, False
    requirements = (FmExists(TCODE_FM, source="ZFM_RR_TCODE_REMOVE.txt",
                             guide=_guide(TCODE_FM, "It needs the local classes include of the function group (see the attached source).")),
                    FmAuthorized(TCODE_FM, group=GROUP), PFCG_AUTH)

    async def run(self, ctx, data):
        try:
            res = await ctx.rfc.call(ctx.system_id, TCODE_FM, IV_ROLE_NAME=data.role, IV_TCODE=data.tcode, IV_TEST_RUN="")
        except RfcError as e:
            return TcodeOut(role=data.role, tcode=data.tcode, success=False, return_type="E", message=f"{e.code}: {e.message}")
        kind = (res.get("EV_RETURN_TYPE") or "E").strip() or "E"
        msg = (res.get("EV_RETURN_MSG") or "").strip()
        more = _ret(res)
        text = (("REVIEW: " if kind == "W" else "") + (msg or "done")) + (f" ({more})" if more else "")
        return TcodeOut(role=data.role, tcode=data.tcode, success=kind in ("S", "W", "I"), return_type=kind, message=text,
                        removed_values=int(res.get("EV_REMOVED_COUNT") or 0))


class DerivedIn(BaseModel):
    role: str


class RegenerateDerived(Task):
    name, Input, Output, idempotent = "pfcg.regenerate_derived", DerivedIn, Done, False
    requirements = (FmExists(DERIVED_FM, source="ZFM_RR_DERIVED_REGENERATE.txt",
                             guide=_guide(DERIVED_FM, "It needs the local classes include of the function group (see the attached source).")),
                    FmAuthorized(DERIVED_FM, group=GROUP))

    async def run(self, ctx, data):
        try:
            res = await ctx.rfc.call(ctx.system_id, DERIVED_FM, IV_ROLE_NAME=data.role, IV_TEST_RUN="")
        except RfcError as e:
            return Done(role=data.role, success=False, message=f"{e.code}: {e.message}. Regenerate the derived roles in PFCG.")
        kind = (res.get("EV_RETURN_TYPE") or "E").strip() or "E"
        msg = (res.get("EV_RETURN_MSG") or "").strip() or ("Derived roles regenerated." if kind in ("S", "W", "I") else "The module returned an error.")
        more = _ret(res)
        return Done(role=data.role, success=kind in ("S", "W", "I"), message=msg + (f" ({more})" if more else ""))
