"""State of a running SAP Software Update Manager (SUM) session, read from its files on the host over SSH (optional SSH access
of the system). Read-only: it never starts, stops or changes SUM."""
from pydantic import BaseModel

from sage.sap import sum as su
from sage.tasks.sum_poll import PollIn, PollSum
from sage.workflows.base import SystemInput, Workflow


class Diagnosis(BaseModel):
    error_code: str
    category: str
    severity: str
    root_cause: str
    recommended_fix: str
    sap_note: str
    auto_recoverable: bool
    matched_text: str


class SumOutput(BaseModel):
    system: str
    state: str
    phase: str
    phase_detail: str
    progress_pct: float | None
    eta: str | None
    time_remaining: str | None
    message: str
    source: str
    required_action: str
    diagnosis: Diagnosis | None = None
    raw_error_context: str | None = None


class SapSumStatus(Workflow):
    name = "sap_sum_status"
    description = ("Read the state of the SAP Software Update Manager (SUM) session on a registered system: RUNNING, WAITING_INPUT, ERROR, "
                   "POSSIBLE_HANG, PROCESS_DEAD, COMPLETED or OFFLINE, with the phase, progress, estimated end and what to do next. For an "
                   "ERROR it matches the end of SAPup.log with known error signatures and gives the cause and the fix. Needs SSH access on "
                   "the system. Read-only: it never starts, stops or changes SUM.")
    schedulable = True
    Input, Output = SystemInput, SumOutput
    tasks = (PollSum,)
    result_states = ("RUNNING", "WAITING_INPUT", "ERROR", "POSSIBLE_HANG", "PROCESS_DEAD", "COMPLETED", "OFFLINE", "UNKNOWN")

    @classmethod
    def result_state(cls, output):
        return output.state

    async def run(self, ctx, data: SystemInput) -> SumOutput:
        p = await ctx.task(PollSum, PollIn())
        action = su.required_action(p.state, p.task_id, p.message, p.phase_detail)
        diag = None
        if p.state == "ERROR":
            found = su.diagnose(f"{p.message}\n{p.log_tail}".strip())
            if found:
                diag = Diagnosis(**found)
                action = f"{action} Diagnosis ({found['error_code']}): {found['root_cause']}"
        return SumOutput(system=ctx.task_ctx.system_label, state=p.state, phase=p.phase, phase_detail=p.phase_detail, progress_pct=p.progress_pct,
                         eta=p.eta, time_remaining=p.time_remaining, message=p.message, source=p.source, required_action=action, diagnosis=diag,
                         raw_error_context=(p.log_tail or None) if p.state == "ERROR" and diag is None else None)
