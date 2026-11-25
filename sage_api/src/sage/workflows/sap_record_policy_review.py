"""Records the AI's reading of a policy document against a request, for the review workflows. Needs no SAP system."""
from sage.tasks.policy_record import RecordIn, RecordOut, RecordPolicyReview
from sage.workflows.base import Workflow


class SapRecordPolicyReview(Workflow):
    name = "sap_record_policy_review"
    description = ("Record your findings after reading a policy document against a role or user-role change request. Only call it when a review "
                   "workflow listed a policy as pending: pass that policy's policy_name, kind, request_hash and fingerprint exactly as given, and one finding "
                   "(role and a short description) for each way the request breaks the policy; an empty list when it meets the policy. Then run the review again. "
                   "Do not record a verdict you did not make by reading the policy text. The first verdict for a request stands.")
    Input, Output = RecordIn, RecordOut
    tasks = (RecordPolicyReview,)

    async def run(self, ctx, data: RecordIn) -> RecordOut:
        return await ctx.task(RecordPolicyReview, data)
