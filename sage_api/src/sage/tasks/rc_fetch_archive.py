import re

from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_FETCH_ANALYSIS in SE37 (function group ZFG_MCPARCHPH, remote-enabled). The attached source says which "
         "internal call builds the ZIP and must be confirmed in a debugger on this system. Not verified on a live system.")


class FetchArchiveIn(BaseModel):
    job_name: str
    job_count: str


class FetchArchiveOut(BaseModel):
    file_path: str
    filename: str
    size_bytes: int


class FetchArchive(Task):
    name, Input, Output = "rc.fetch_archive", FetchArchiveIn, FetchArchiveOut
    requirements = (FmExists("ZFM_RC_FETCH_ANALYSIS", guide=GUIDE, source="ZFM_RC_FETCH_ANALYSIS.txt"),
                    FmAuthorized("ZFM_RC_FETCH_ANALYSIS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_FETCH_ANALYSIS", JOBNAME=data.job_name, JOBCOUNT=data.job_count)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(res["FILENAME"])) or "readiness.zip"
        folder = ctx.data_dir / "downloads" / (ctx.system_label or str(ctx.system_id))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{data.job_name}-{data.job_count}-{name}"
        blob = bytes(res["ZIP_DATA"])
        path.write_bytes(blob)
        return FetchArchiveOut(file_path=str(path), filename=name, size_bytes=len(blob))
