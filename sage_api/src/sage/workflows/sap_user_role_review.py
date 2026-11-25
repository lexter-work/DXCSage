"""Review a request to assign or unassign roles for SAP users, without changing anything: do the users and roles exist,
which changes are no-ops, and would a change add a segregation-of-duties conflict. Read-only."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import TableReadable
from sage.sap.sod import normalize_rules
from sage.sap.userrole_review import Change, Review, review
from sage.util import utcnow
from sage.workflows.base import SystemInput, Workflow

TABLES = ("USR02", "AGR_USERS", "AGR_DEFINE", "AGR_AGRS", "AGR_1251")


class ReviewInput(SystemInput):
    changes: list[Change]


class SapUserRoleReview(Workflow):
    name = "sap_user_role_review"
    description = ("Review a request to assign or unassign roles for SAP users before anyone changes anything: checks that the "
                   "users and roles exist, flags changes that do nothing, and compares each user's roles before and after with the "
                   "SoD matrix. 'ready' is false when there is an error or the change would add a CRITICAL conflict. Read-only. "
                   "To apply the changes use sap_user_role_change.")
    Input, Output = ReviewInput, Review
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in TABLES)

    async def run(self, ctx, data: ReviewInput) -> Review:
        async def settings():
            return {"matrix": await ctx.task_ctx.settings.get("sod.matrix"), "max": await ctx.task_ctx.settings.get("rolechange.max_entries"),
                    "day": utcnow().strftime("%Y%m%d")}
        cfg = await ctx.snapshot("review_config", settings)
        try:
            rules = normalize_rules(cfg["matrix"])
        except ValueError as e:
            raise WorkflowFailed(str(e)) from e
        return await review(ctx, data.changes, rules, cfg["day"], int(cfg["max"]))
