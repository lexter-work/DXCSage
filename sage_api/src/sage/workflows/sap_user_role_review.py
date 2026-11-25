"""Review a request to assign or unassign roles for SAP users, without changing anything: do the users and roles exist,
which changes are no-ops, and would a change add a segregation-of-duties conflict. Read-only."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import TableReadable
from sage.sap.sod import normalize_rules
from sage.sap.request_input import request_changes
from sage.policies import request_hash
from sage.sap.userrole_review import Change, Review, clean, review
from sage.util import utcnow
from sage.workflows.base import SystemInput, Workflow

TABLES = ("USR02", "AGR_USERS", "AGR_DEFINE", "AGR_AGRS", "AGR_1251")


class ReviewInput(SystemInput):
    changes: list[Change] = []
    file_id: str | None = None
    policy_name: str | None = None      # one more policy to check; policies marked required are always checked


async def policy_args(ctx, raw, extra: str | None) -> list[dict]:
    """What the AI recorded for each policy and this exact request (None = it still has to review)."""
    if ctx.task_ctx.policies is None:
        return []
    cleaned, _ = clean(raw, 10 ** 6)
    h = request_hash("user_role", [c.model_dump() for c in cleaned])
    return await ctx.snapshot("policies", lambda: ctx.task_ctx.policies.status_for([extra or ""], "user_role", h))


class SapUserRoleReview(Workflow):
    name = "sap_user_role_review"
    description = ("Review a request to assign or unassign roles for SAP users before anyone changes anything: checks that the "
                   "users and roles exist, flags changes that do nothing, and compares each user's roles before and after with the "
                   "SoD matrix. 'ready' is false when there is an error or the change would add a CRITICAL conflict. Read-only. "
                   "To apply the changes use sap_user_role_change. " +
                   "Give the changes in the `changes` list (fill it from what the user wrote; no Excel file is needed) or pass the `file_id` of an Excel file the user attached (the file_id is in their message). Not both. ")
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
        raw, errs = await request_changes(ctx, data.changes, data.file_id, ["user_roles"], lambda r: Change(**r))
        return await review(ctx, raw, rules, cfg["day"], int(cfg["max"]), errs, await policy_args(ctx, raw, data.policy_name))
