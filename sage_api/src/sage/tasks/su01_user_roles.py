from pydantic import BaseModel

from sage.sap.requirements import DeclaredAuth, FmAuthorized, FmExists
from sage.tasks.base import Task

GET, ASSIGN, COMMIT = "BAPI_USER_GET_DETAIL", "BAPI_USER_ACTGROUPS_ASSIGN", "BAPI_TRANSACTION_COMMIT"
STD = "Standard SAP function module, delivered with every system. If it is missing, the system is not a normal ABAP application server."
# Typical authorizations for changing role assignments with these BAPIs. Not verified on a system: confirm with the security team.
ASSIGN_AUTH = DeclaredAuth(key="user role assignment", rows=(
    ("S_USER_GRP", "CLASS", "*"), ("S_USER_GRP", "ACTVT", "02"), ("S_USER_AGR", "ACT_GROUP", "*"), ("S_USER_AGR", "ACTVT", "22")),
    guide="Needed to change which roles a user holds. These are the usual values; the security team may scope them to user groups and role names.")


class ChangeIn(BaseModel):
    username: str
    assign: list[str] = []
    unassign: list[str] = []
    valid_from: str                 # YYYYMMDD for new assignments (given by the workflow so a replay uses the same date)


class Outcome(BaseModel):
    role: str
    action: str
    success: bool
    note: str


class ChangeOut(BaseModel):
    username: str
    outcomes: list[Outcome]


def _error(ret) -> str | None:
    for row in ret if isinstance(ret, list) else [ret or {}]:
        if row.get("TYPE") in ("E", "A"):
            return row.get("MESSAGE") or row["TYPE"]
    return None


class ChangeUserRoles(Task):
    """Changes the roles of one user. WRITES to SAP, so it is never re-run after an interrupted attempt.

    BAPI_USER_ACTGROUPS_ASSIGN replaces the user's whole role list, so the task reads the list, applies the change,
    writes it, commits, reads it back and reports each change by what the user really holds afterwards."""
    name, Input, Output, idempotent = "su01.change_user_roles", ChangeIn, ChangeOut, False
    requirements = (*[FmExists(f, guide=STD) for f in (GET, ASSIGN, COMMIT)], *[FmAuthorized(f) for f in (GET, ASSIGN, COMMIT)], ASSIGN_AUTH)

    async def run(self, ctx, data):
        async def read():
            d = await ctx.rfc.call(ctx.system_id, GET, USERNAME=data.username)
            err = _error(d.get("RETURN"))
            return err if err else [dict(r) for r in d.get("ACTIVITYGROUPS") or []]

        plan = [(r, "assign") for r in data.assign] + [(r, "unassign") for r in data.unassign]

        def fail(msg):
            return ChangeOut(username=data.username, outcomes=[Outcome(role=r, action=a, success=False, note=msg) for r, a in plan])

        current = await read()
        if isinstance(current, str):
            return fail(f"Could not read {data.username}: {current}")
        held = {r["AGR_NAME"] for r in current}
        wanted = (held | set(data.assign)) - set(data.unassign)
        if wanted != held:
            final = [r for r in current if r["AGR_NAME"] in wanted]
            final += [{"AGR_NAME": n, "FROM_DAT": data.valid_from, "TO_DAT": "99991231"} for n in sorted(wanted - held)]
            res = await ctx.rfc.call(ctx.system_id, ASSIGN, USERNAME=data.username, ACTIVITYGROUPS=final)
            err = _error(res.get("RETURN"))
            if err:
                return fail(f"{ASSIGN} failed for {data.username}: {err}")
            await ctx.rfc.call(ctx.system_id, COMMIT, WAIT="X")
        after = await read()
        if isinstance(after, str):
            return fail(f"Changed {data.username} but could not read it back to verify: {after}")
        now = {r["AGR_NAME"] for r in after}
        out = []
        for role, action in plan:
            ok = (role in now) == (action == "assign")
            verb = "Assigned" if action == "assign" else "Unassigned"
            note = (f"{verb} {role}." if ok else f"{role} is still {'not assigned' if action == 'assign' else 'assigned'} after the change.")
            out.append(Outcome(role=role, action=action, success=ok, note=note))
        return ChangeOut(username=data.username, outcomes=out)
