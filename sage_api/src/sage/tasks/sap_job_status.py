from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.sap.rfc import RfcError
from sage.tasks.base import Task

# BTCSTATUS. "X" mirrors the old watcher; "A" (aborted) is added here: both end the job unsuccessfully. Unverified on a live system.
LABELS = {"R": "running", "Y": "ready", "P": "scheduled", "S": "released", "F": "finished", "A": "aborted", "X": "failed"}
GUIDE = ("Create ZFM_CHECK_JOB_STATUS in SE37 (function group ZFG_MCPARCHPH, remote-enabled), wrapping "
         "BP_JOB_STATUS_GET. Skip it only if calling BP_JOB_STATUS_GET directly over RFC works in this system.")


class JobStatusIn(BaseModel):
    job_name: str
    job_count: str


class JobStatusOut(BaseModel):
    found: bool
    status_code: str = ""
    status_label: str = ""
    terminal: bool = False
    failed: bool = False


class JobStatus(Task):
    """Shared by any workflow that schedules a background job."""
    name, Input, Output = "sap.job_status", JobStatusIn, JobStatusOut
    requirements = (FmExists("ZFM_CHECK_JOB_STATUS", guide=GUIDE, source="ZFM_CHECK_JOB_STATUS.txt"),
                    FmAuthorized("ZFM_CHECK_JOB_STATUS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        try:
            res = await ctx.rfc.call(ctx.system_id, "ZFM_CHECK_JOB_STATUS", JOBNAME=data.job_name, JOBCOUNT=data.job_count)
        except RfcError as e:
            if "JOB_NOT_FOUND" in e.message or "JOB_NOT_FOUND" in e.code:
                return JobStatusOut(found=False)
            raise
        code = (res.get("STATUS") or "").strip()
        return JobStatusOut(found=True, status_code=code, status_label=LABELS.get(code, code or "unknown"),
                            terminal=code in ("F", "A", "X"), failed=code in ("A", "X"))
