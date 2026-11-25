from typing import Literal

from pydantic import BaseModel

from sage.policies import Finding, PolicyError
from sage.tasks.base import Task


class RecordIn(BaseModel):
    policy_name: str
    kind: Literal["user_role", "role_auth"]
    request_hash: str
    fingerprint: str
    findings: list[Finding] = []


class RecordOut(BaseModel):
    recorded: bool
    message: str


class RecordPolicyReview(Task):
    """Stores what the AI found when it read a policy against a request. No SAP access. The first verdict for a policy and request stands."""
    name, Input, Output = "policy.record_review", RecordIn, RecordOut

    async def run(self, ctx, data):
        try:
            msg = await ctx.policies.record(data.policy_name, data.fingerprint, data.kind, data.request_hash, [f.model_dump() for f in data.findings], ctx.actor)
        except PolicyError as e:
            return RecordOut(recorded=False, message=str(e))
        return RecordOut(recorded=True, message=msg)
