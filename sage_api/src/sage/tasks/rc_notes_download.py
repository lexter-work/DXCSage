from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_NOTES_DOWNLOAD (class plus remote-enabled function module) as in the attached source. "
         "It wraps CL_SCWN_DARK_API=>SCHEDULE_DOWNLOAD and only downloads notes; implementing a note stays manual in SNOTE.")


class NotesDownloadIn(BaseModel):
    notes: list[str]


class NotesDownloadOut(BaseModel):
    schedule_id: str = ""
    run_id: str = ""
    job_count: str = ""
    messages: list[str] = []


class NotesDownload(Task):
    name, Input, Output, idempotent = "rc.notes_download", NotesDownloadIn, NotesDownloadOut, False
    requirements = (FmExists("ZFM_RC_NOTES_DOWNLOAD", guide=GUIDE, source="ZFM_RC_NOTES_DOWNLOAD.txt"),
                    FmAuthorized("ZFM_RC_NOTES_DOWNLOAD", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        # Unverified: row shape of IT_NOTES (type CWB_T_NOTE). Check in SE11 and adjust the key if it is not NUMM.
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_NOTES_DOWNLOAD", IT_NOTES=[{"NUMM": n.rjust(10, "0")} for n in data.notes])
        msgs = [str(r.get("MESSAGE", "")) for r in res.get("ET_RETURN", [])]
        return NotesDownloadOut(schedule_id=str(res.get("EV_SCHEDULE_ID", "")), run_id=str(res.get("EV_RUN_ID", "")),
                                job_count=str(res.get("EV_JOB_COUNT", "")), messages=msgs)
