from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_START_ANALYSIS in SE37 (function group ZFG_MCPARCHPH, remote-enabled) as in the attached source. "
         "JOB_OPEN, JOB_SUBMIT and JOB_CLOSE are not remote-enabled, so this wrapper runs them inside SAP. "
         "The RFC user's role also needs S_BTCH_JOB (JOBACTION = RELE).")


class StartAnalysisIn(BaseModel):
    job_name: str
    variant: str


class StartAnalysisOut(BaseModel):
    job_name: str
    job_count: str


class StartAnalysis(Task):
    name, Input, Output, idempotent = "rc.start_analysis", StartAnalysisIn, StartAnalysisOut, False
    requirements = (FmExists("ZFM_RC_START_ANALYSIS", guide=GUIDE, source="ZFM_RC_START_ANALYSIS.txt"),
                    FmAuthorized("ZFM_RC_START_ANALYSIS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_START_ANALYSIS", JOBNAME=data.job_name, VARIANT=data.variant)
        return StartAnalysisOut(job_name=str(res["REAL_JOBNAME"]).strip(), job_count=str(res["JOBCOUNT"]).strip())
