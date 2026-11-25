"""Change the authorizations of SAP roles. WRITES to SAP. It runs the same review as sap_role_auth_review first and
changes nothing when the review has an error, a policy violation or a new CRITICAL SoD conflict."""
from pydantic import BaseModel

from sage.sap.requirements import TableReadable
from sage.sap.request_input import request_changes
from sage.sap.roleauth_review import Review, RoleChange
from sage.tasks.pfcg_role_auth import ChangeRoleAuth, DerivedIn, Done, RegenerateDerived, RemoveTcode, RoleChangeIn, TcodeIn, TcodeOut, Value
from sage.workflows.base import Workflow
from sage.workflows.sap_role_auth_review import TABLES, ReviewInput, load, review


class ChangeOutput(BaseModel):
    executed: bool
    review: Review
    changes_applied: list[Done]
    tcode_results: list[TcodeOut]
    derived_regenerated: list[Done]
    message: str


class SapRoleAuthChange(Workflow):
    name = "sap_role_auth_change"
    description = ("CHANGES SAP: adds, removes or modifies authorization values on roles and removes transaction codes from roles "
                   "(custom function modules that drive PFCG), then regenerates the derived roles of every changed parent role. "
                   "Always ask the requester to confirm the exact list of changes before you call it. It first runs the review and "
                   "refuses on any error, policy violation or new CRITICAL SoD conflict. Roles are changed one at a time: if a role "
                   "fails, the roles before it stay changed. Use sap_role_auth_review to preview. " +
                   "Give the changes in the `changes` list (fill it from what the user wrote; no Excel file is needed) or pass the `file_id` of an Excel file the user attached (the file_id is in their message). Not both. ")
    Input, Output = ReviewInput, ChangeOutput
    tasks = (ChangeRoleAuth, RemoveTcode, RegenerateDerived)
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in TABLES)

    async def run(self, ctx, data: ReviewInput) -> ChangeOutput:
        policy, rules = await load(ctx)
        raw, errs = await request_changes(ctx, data.changes, data.file_id, ["role_auth", "tcode_removal"], lambda r: RoleChange(**r))
        rv = await review(ctx, raw, policy, rules, errs)
        empty = ChangeOutput(executed=False, review=rv, changes_applied=[], tcode_results=[], derived_regenerated=[], message="")
        if not rv.ready:
            return empty.model_copy(update={"message": "Nothing was changed: " + " ".join(rv.errors)})

        applied, tcodes, derived = [], [], []
        for role in sorted({c.role for c in rv.changes}):
            mine = [c for c in rv.changes if c.role == role]
            adds = [Value(object=c.object, field=c.field, low=c.value) for c in mine if c.action in ("add", "modify")]
            dels = [Value(object=c.object, field=c.field, low=c.value if c.action == "remove" else c.current_value) for c in mine if c.action in ("remove", "modify")]
            ok = True
            if adds or dels:
                done = await ctx.task(ChangeRoleAuth, RoleChangeIn(role=role, adds=adds, deletes=dels))
                applied.append(done)
                ok = done.success
            for c in (x for x in mine if x.action == "remove_tcode"):
                if not ok:
                    break
                t = await ctx.task(RemoveTcode, TcodeIn(role=role, tcode=c.value))
                tcodes.append(t)
                ok = t.success
            if ok and any(r.role == role and r.derived_children for r in rv.roles):
                derived.append(await ctx.task(RegenerateDerived, DerivedIn(role=role)))
            if not ok:
                break                               # stop at the first failed role; the others stay untouched
        failed = [r for r in (*applied, *tcodes, *derived) if not r.success]
        return ChangeOutput(executed=True, review=rv, changes_applied=applied, tcode_results=tcodes, derived_regenerated=derived,
                            message=("Changed SAP." if not failed else f"STOPPED: {len(failed)} step(s) failed, see the results. Roles after the failed one were not touched.")
                            + " Check the roles in PFCG.")
