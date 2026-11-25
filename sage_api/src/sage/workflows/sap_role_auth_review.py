"""Review a request to change the authorizations of SAP roles without changing anything: do the roles and values exist,
does the change meet the policy (setting rolechange.policy), and would it add a segregation-of-duties conflict. Read-only."""
from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import TableReadable
from sage.sap.request_input import request_changes
from sage.policies import request_hash
from sage.sap.roleauth_review import Review, RoleChange, clean, review
from sage.sap.sod import normalize_rules
from sage.workflows.base import SystemInput, Workflow

TABLES = ("AGR_DEFINE", "AGR_AGRS", "AGR_1251", "AGR_TCODES")


class ReviewInput(SystemInput):
    changes: list[RoleChange] = []
    file_id: str | None = None
    policy_name: str | None = None      # one more policy to check; policies marked required are always checked


async def load(ctx):
    async def settings():
        return {"matrix": await ctx.task_ctx.settings.get("sod.matrix"), "policy": await ctx.task_ctx.settings.get("rolechange.policy")}
    cfg = await ctx.snapshot("review_config", settings)
    try:
        return cfg["policy"], normalize_rules(cfg["matrix"])
    except ValueError as e:
        raise WorkflowFailed(str(e)) from e


async def policy_args(ctx, raw, policy, extra: str | None) -> list[dict]:
    """What the AI recorded for each policy and this exact request (None = it still has to review)."""
    if ctx.task_ctx.policies is None:
        return []
    cleaned, _ = clean(raw, int(policy.get("max_changes_per_request", 50)) + 10 ** 6)
    h = request_hash("role_auth", [c.model_dump() for c in cleaned])
    return await ctx.snapshot("policies", lambda: ctx.task_ctx.policies.status_for([extra or ""], "role_auth", h))


class SapRoleAuthReview(Workflow):
    name = "sap_role_auth_review"
    description = ("Review a request to change role authorizations (add, remove or modify an authorization value, or remove a transaction "
                   "code from a role) before anyone changes anything: checks that the roles, objects and values exist, flags derived and "
                   "composite roles, applies the policy (restricted objects, wildcard, activity levels, SAP_* roles, request size) and "
                   "compares the role with the SoD matrix before and after. 'ready' is false on any error, policy violation or new "
                   "CRITICAL conflict. Read-only. To apply the changes use sap_role_auth_change. " +
                   "Give the changes in the `changes` list (fill it from what the user wrote; no Excel file is needed) or pass the `file_id` of an Excel file the user attached (the file_id is in their message). Not both. ")
    Input, Output = ReviewInput, Review
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in TABLES)

    async def run(self, ctx, data: ReviewInput) -> Review:
        policy, rules = await load(ctx)
        raw, errs = await request_changes(ctx, data.changes, data.file_id, ["role_auth", "tcode_removal"], lambda r: RoleChange(**r))
        return await review(ctx, raw, policy, rules, errs, await policy_args(ctx, raw, policy, data.policy_name))
