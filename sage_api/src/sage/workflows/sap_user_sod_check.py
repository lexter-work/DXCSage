"""Check one SAP user's roles for segregation-of-duties conflicts against the SoD matrix (setting sod.matrix).
Read-only: AGR_USERS, AGR_AGRS, AGR_1251 and USR02 through RFC_READ_TABLE."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import TableReadable
from sage.sap.roles import Conflict, assigned_roles, existing_users, role_data, with_children
from sage.sap.sod import SAFE, conflicts_for_roles, normalize_rules
from sage.util import utcnow
from sage.workflows.base import SystemInput, Workflow


class SodInput(SystemInput):
    username: str


class SodOutput(BaseModel):
    username: str
    user_exists: bool
    roles_checked: list[str]
    unverified_roles: list[str]
    total_conflicts: int
    has_critical: bool
    conflicts: list[Conflict]
    message: str


class SapUserSodCheck(Workflow):
    name = "sap_user_sod_check"
    description = ("Check whether one SAP user already has a toxic combination of access: reads the user's currently valid roles "
                   "(composite roles expanded) and their authorizations, and compares them with the SoD rule matrix. A conflict can "
                   "come from different roles. Read-only. Roles with a wildcard in S_TCODE are matched by exact value only.")
    schedulable = True
    Input, Output = SodInput, SodOutput
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in ("USR02", "AGR_USERS", "AGR_AGRS", "AGR_1251"))
    tasks = ()

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

        def empty(exists, msg):
            return SodOutput(username=user, user_exists=exists, roles_checked=[], unverified_roles=[], total_conflicts=0,
                             has_critical=False, conflicts=[], message=msg)

        if user not in await existing_users(ctx, [user]):
            return empty(False, f"User {user} does not exist on this system.")
        direct = (await assigned_roles(ctx, [user], day))[user]
        if not direct:
            return empty(True, f"{user} has no currently valid role assignment.")
        roles = await with_children(ctx, direct)
        rdata, unverified = await role_data(ctx, roles, rules)
        found = conflicts_for_roles(rules, sorted(roles), rdata)
        crit = any(c["severity"] == "CRITICAL" for c in found)
        msg = (f"Checked {user}'s {len(roles)} role(s) ({len(direct)} assigned directly): {len(found)} SoD conflict(s)."
               + (" CRITICAL conflicts found." if crit else " No critical conflicts."))
        if unverified:
            msg += f" Could not read the authorizations of {', '.join(unverified)} completely, so a conflict there may be missing."
        return SodOutput(username=user, user_exists=True, roles_checked=sorted(roles), unverified_roles=unverified,
                         total_conflicts=len(found), has_critical=crit, conflicts=[Conflict(**c) for c in found], message=msg)
