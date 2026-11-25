"""Assign or unassign roles for SAP users. WRITES to SAP. It runs the same review as sap_user_role_review first and
changes nothing when the review has an error or the change would add a CRITICAL SoD conflict."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.sod import normalize_rules
from sage.sap.request_input import request_changes
from sage.sap.userrole_review import Change, Review, review
from sage.tasks.su01_user_roles import ChangeIn, ChangeUserRoles, Outcome
from sage.util import utcnow
from sage.workflows.sap_user_role_review import TABLES, ReviewInput, policy_args
from sage.workflows.base import Workflow
from sage.sap.requirements import TableReadable


class ChangeOutput(BaseModel):
    executed: bool
    review: Review
    results: list[Outcome]
    message: str


class SapUserRoleChange(Workflow):
    name = "sap_user_role_change"
    description = ("CHANGES SAP: assigns or unassigns roles for users (BAPI_USER_ACTGROUPS_ASSIGN), then reads each user back to verify. "
                   "Always ask the requester to confirm the exact list of changes before you call it. It first runs the review and "
                   "refuses if there is an error or the change would add a CRITICAL segregation-of-duties conflict. "
                   "Use sap_user_role_review to preview. " +
                   "Give the changes in the `changes` list (fill it from what the user wrote; no Excel file is needed) or pass the `file_id` of an Excel file the user attached (the file_id is in their message). Not both. ")
    Input, Output = ReviewInput, ChangeOutput
    tasks = (ChangeUserRoles,)
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in TABLES)

    async def run(self, ctx, data: ReviewInput) -> ChangeOutput:
        async def settings():
            return {"matrix": await ctx.task_ctx.settings.get("sod.matrix"), "max": await ctx.task_ctx.settings.get("rolechange.max_entries"),
                    "day": utcnow().strftime("%Y%m%d")}
        cfg = await ctx.snapshot("review_config", settings)
        try:
            rules = normalize_rules(cfg["matrix"])
        except ValueError as e:
            raise WorkflowFailed(str(e)) from e
        raw, errs = await request_changes(ctx, data.changes, data.file_id, ["user_roles"], lambda r: Change(**r))
        rv = await review(ctx, raw, rules, cfg["day"], int(cfg["max"]), errs, await policy_args(ctx, raw, data.policy_name))
        if not rv.ready:
            return ChangeOutput(executed=False, review=rv, results=[], message="Nothing was changed: " + " ".join(rv.errors))
        if not rv.changes:
            return ChangeOutput(executed=False, review=rv, results=[], message="Nothing to do: every change is already in place.")
        results = []
        for user in sorted({c.username for c in rv.changes}):
            mine = [c for c in rv.changes if c.username == user]
            out = await ctx.task(ChangeUserRoles, ChangeIn(username=user, valid_from=cfg["day"],
                                                           assign=[c.role for c in mine if c.action == "assign"],
                                                           unassign=[c.role for c in mine if c.action == "unassign"]))
            results += out.outcomes
        bad = [r for r in results if not r.success]
        return ChangeOutput(executed=True, review=rv, results=results,
                            message=f"Changed SAP: {len(results) - len(bad)} of {len(results)} change(s) verified." + (f" {len(bad)} failed: see results." if bad else ""))
