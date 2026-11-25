"""Check one SAP user's roles for segregation-of-duties conflicts against the SoD matrix (setting sod.matrix).
Read-only: AGR_USERS, AGR_AGRS, AGR_1251 and USR02 through RFC_READ_TABLE."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import TableReadable
from sage.sap.sod import SAFE, conflicts_for_roles, normalize_rules, sides
from sage.tasks.sap_read_table import ReadTable, ReadTableIn
from sage.util import utcnow
from sage.workflows.base import SystemInput, Workflow


class SodInput(SystemInput):
    username: str


class Conflict(BaseModel):
    rule_id: str
    severity: str
    roles: list[str]
    conflicting_objects: str
    rule_description: str
    recommendation: str


class SodOutput(BaseModel):
    username: str
    user_exists: bool
    roles_checked: list[str]
    unverified_roles: list[str]
    total_conflicts: int
    has_critical: bool
    conflicts: list[Conflict]
    message: str


def _any(field, values):
    return " OR ".join(f"{field} = '{v}'" for v in values)


class SapUserSodCheck(Workflow):
    name = "sap_user_sod_check"
    description = ("Check whether one SAP user already has a toxic combination of access: reads the user's currently valid roles "
                   "(composite roles expanded) and their authorizations, and compares them with the SoD rule matrix. A conflict can "
                   "come from different roles. Read-only. Roles with a wildcard in S_TCODE are matched by exact value only.")
    Input, Output = SodInput, SodOutput
    tasks = (ReadTable,)
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in ("USR02", "AGR_USERS", "AGR_AGRS", "AGR_1251"))

    async def run(self, ctx, data: SodInput) -> SodOutput:
        user = data.username.strip().upper()
        if not SAFE.match(user) or len(user) > 12:
            raise WorkflowFailed("Invalid user name. Use the SAP user ID (letters, digits, and _ . - / $ # @, up to 12 characters).")

        async def matrix():
            return await ctx.task_ctx.settings.get("sod.matrix")

        async def today():
            return utcnow().strftime("%Y%m%d")
        try:
            rules = normalize_rules(await ctx.snapshot("sod_matrix", matrix))
        except ValueError as e:
            raise WorkflowFailed(str(e)) from e
        day = await ctx.snapshot("today", today)

        who = await ctx.task(ReadTable, ReadTableIn(table="USR02", fields=["BNAME"], where=f"BNAME = '{user}'", rows=1))
        if not who.rows:
            return SodOutput(username=user, user_exists=False, roles_checked=[], unverified_roles=[], total_conflicts=0, has_critical=False,
                             conflicts=[], message=f"User {user} does not exist on this system.")

        asg = await ctx.task(ReadTable, ReadTableIn(table="AGR_USERS", fields=["AGR_NAME", "FROM_DAT", "TO_DAT"], where=f"UNAME = '{user}'"))
        direct = sorted({r["AGR_NAME"].strip() for r in asg.rows
                         if r["AGR_NAME"].strip() and (not r["FROM_DAT"].strip() or r["FROM_DAT"] <= day) and (not r["TO_DAT"].strip() or r["TO_DAT"] >= day)})
        if not direct:
            return SodOutput(username=user, user_exists=True, roles_checked=[], unverified_roles=[], total_conflicts=0, has_critical=False,
                             conflicts=[], message=f"{user} has no currently valid role assignment.")

        roles = set(direct)
        usable = [r for r in direct if SAFE.match(r)]
        if usable:
            comp = await ctx.task(ReadTable, ReadTableIn(table="AGR_AGRS", fields=["AGR_NAME", "CHILD_AGR"], where=_any("AGR_NAME", usable)))
            roles |= {r["CHILD_AGR"].strip() for r in comp.rows if r["CHILD_AGR"].strip()}

        values = sorted({v for rule in rules for v, _ in sides(rule)})
        grants = f"( OBJECT = 'S_TCODE' AND FIELD = 'TCD' AND ( {_any('LOW', values)} ) )"
        wanted = f"( {_any('OBJECT', values)} OR {grants} )"
        role_data, unverified = {}, []
        for role in sorted(roles):
            if not SAFE.match(role):
                unverified.append(role)
                role_data[role] = {"objects": set(), "tcodes": set(), "activities": {}}
                continue
            r = await ctx.task(ReadTable, ReadTableIn(table="AGR_1251", fields=["OBJECT", "FIELD", "LOW"],
                                                      where=f"AGR_NAME = '{role}' AND DELETED = ' ' AND {wanted}"))
            if r.truncated:
                unverified.append(role)
            d = {"objects": set(), "tcodes": set(), "activities": {}}
            for row in r.rows:
                obj, fld, low = row["OBJECT"].strip(), row["FIELD"].strip(), row["LOW"].strip()
                if obj == "S_TCODE" and fld == "TCD":
                    d["tcodes"].add(low)
                else:
                    d["objects"].add(obj)
            role_data[role] = d
        # activities of the objects named by rules, in a second pass per role only where a rule scopes by activity
        scoped = sorted({v for rule in rules for (v, a) in sides(rule) if a})
        if scoped:
            for role in sorted(roles):
                if not SAFE.match(role) or role not in role_data or not (role_data[role]["objects"] & set(scoped)):
                    continue
                r = await ctx.task(ReadTable, ReadTableIn(table="AGR_1251", fields=["OBJECT", "LOW"],
                                                          where=f"AGR_NAME = '{role}' AND DELETED = ' ' AND FIELD = 'ACTVT' AND ( {_any('OBJECT', scoped)} )"))
                if r.truncated and role not in unverified:
                    unverified.append(role)
                for row in r.rows:
                    if row["LOW"].strip():
                        role_data[role]["activities"].setdefault(row["OBJECT"].strip(), set()).add(row["LOW"].strip())

        found = conflicts_for_roles(rules, sorted(roles), role_data)
        crit = any(c["severity"] == "CRITICAL" for c in found)
        msg = (f"Checked {user}'s {len(roles)} role(s) ({len(direct)} assigned directly): {len(found)} SoD conflict(s)."
               + (" CRITICAL conflicts found." if crit else " No critical conflicts."))
        if unverified:
            msg += f" Could not read the authorizations of {', '.join(sorted(unverified))} completely, so a conflict there may be missing."
        return SodOutput(username=user, user_exists=True, roles_checked=sorted(roles), unverified_roles=sorted(unverified),
                         total_conflicts=len(found), has_critical=crit, conflicts=[Conflict(**c) for c in found], message=msg)
