"""Find obsolete transaction codes in role menus with SU25 step 2D (PROFGEN_CORR_REPORT_2).
Durable: schedules a background job, waits for it, then reads its spool. Read-only for roles: it only reports."""
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import DeclaredAuth
from sage.tasks.sap_job_status import JobStatus, JobStatusIn
from sage.tasks.su25_obsolete_tcodes import Entry, FetchResult, FetchIn, StartIn, StartScan
from sage.workflows.base import SystemInput, Workflow

# Checked by the report itself inside the background job (confirmed on one system: without S_USER_AGR it ends with no spool).
JOB_AUTH = DeclaredAuth(key="PROFGEN_CORR_REPORT_2", rows=(
    ("S_USER_AGR", "ACTVT", "03"), ("S_USER_AGR", "ACT_GROUP", "*"), ("S_BTCH_ADM", "BTCADMIN", "Y")),
    guide="The standard report checks these inside the background job. Without S_USER_AGR it finishes without a result list.")


class ObsoleteOutput(BaseModel):
    job_name: str
    job_count: str
    total: int
    roles: int
    sample: list[Entry]
    file_path: str
    note: str = ""


class SapObsoleteTcodes(Workflow):
    name = "sap_obsolete_tcodes"
    description = ("Find obsolete transaction codes in the role menus of a registered SAP system (SU25 step 2D, report "
                   "PROFGEN_CORR_REPORT_2, all roles). Runs as a background job that can take a long time. Returns the role and "
                   "transaction pairs SAP would delete, the first 100 inline and all of them in a CSV file. Read-only: it changes no role.")
    Input, Output, durable = SystemInput, ObsoleteOutput, True
    schedulable, schedule_min_minutes = True, 1440     # starts a SAP job: at most once a day
    tasks = (StartScan, JobStatus, FetchResult)
    extra_requirements = (JOB_AUTH,)

    async def run(self, ctx, data: SystemInput) -> ObsoleteOutput:
        job = await ctx.task(StartScan, StartIn(job_name=f"ZRR_TC_OBS_{ctx.run_id}_{ctx.tool_call_id}"))
        final = await ctx.wait(JobStatus, JobStatusIn(job_name=job.job_name, job_count=job.job_count),
                               until=lambda o: (not o.found) or o.terminal)
        if not final.found:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} was not found on the system.")
        if final.failed:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} ended {final.status_label}. Check SM37 on the system.")
        res = await ctx.task(FetchResult, FetchIn(job_name=job.job_name, job_count=job.job_count))
        note = "" if res.total else (
            f"The scan finished but the spool holds no obsolete transactions ({res.lines_read} lines read). If the job log shows "
            "'not authorized to use transaction PFCG' or S_USER_AGR, the RFC user lacks that authorization and the report made no list.")
        return ObsoleteOutput(job_name=job.job_name, job_count=job.job_count, total=res.total, roles=res.roles,
                              sample=res.sample, file_path=res.file_path, note=note)
