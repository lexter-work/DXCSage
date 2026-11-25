import csv
import re

from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

START_FM, FETCH_FM = "ZFM_RR_TC_OBS_START", "ZFM_RR_TC_OBS_FETCH"
START_GUIDE = ("Create ZFM_RR_TC_OBS_START in SE37 (function group ZFG_MCPARCHPH, remote-enabled) as in the attached source. "
               "It runs JOB_OPEN, JOB_SUBMIT and JOB_CLOSE inside SAP for the report PROFGEN_CORR_REPORT_2 (SU25 step 2D). "
               "The RFC user's role also needs S_BTCH_JOB (JOBACTION = RELE), S_BTCH_ADM (BTCADMIN = Y) and S_USER_AGR (ACTVT 03).")
FETCH_GUIDE = ("Create ZFM_RR_TC_OBS_FETCH in SE37 (function group ZFG_MCPARCHPH, remote-enabled) as in the attached source. "
               "It reads the finished job's spool with RSPO_RETURN_ABAP_SPOOLJOB. Its LISTLINES table is typed SOLI_TAB.")
REMOVED = "old entry will be deleted"


class StartIn(BaseModel):
    job_name: str


class StartOut(BaseModel):
    job_name: str
    job_count: str


class StartScan(Task):
    """Schedules the SU25 step 2D report (obsolete transactions in role menus) as an immediate background job."""
    name, Input, Output, idempotent = "su25.start_obsolete_scan", StartIn, StartOut, False
    requirements = (FmExists(START_FM, guide=START_GUIDE, source="ZFM_RR_TC_OBS_START.txt"),
                    FmAuthorized(START_FM, group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, START_FM, JOBNAME=data.job_name, VARIANT="")
        return StartOut(job_name=str(res["REAL_JOBNAME"]).strip(), job_count=str(res["JOBCOUNT"]).strip())


def parse_lines(lines: list[str]) -> list[dict]:
    """Pipe-delimited spool lines -> {role, tcode} for rows flagged "Old entry will be deleted".

    Field order (confirmed on one system, 2026-09-22): status, role, description, node id, label "Transaction", tcode,
    automatic adjustment, info, does not exist, locked, obsolete. Rows with fewer than 7 fields are skipped."""
    out = []
    for raw in lines:
        parts = [p.strip() for p in raw.split("|")]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) < 7 or not parts[1] or not parts[5] or parts[6].lower() != REMOVED:
            continue
        out.append({"role": parts[1].upper(), "tcode": parts[5].upper(), "description": parts[2], "node_id": parts[3]})
    return out


class FetchIn(BaseModel):
    job_name: str
    job_count: str


class Entry(BaseModel):
    role: str
    tcode: str


class FetchOut(BaseModel):
    spool_number: str
    lines_read: int
    total: int                      # obsolete tcode entries found
    roles: int
    sample: list[Entry]             # first 100 only; the full list is in file_path
    file_path: str = ""


class FetchResult(Task):
    """Reads the finished job's spool and extracts the (role, obsolete transaction) pairs SAP flagged for removal."""
    name, Input, Output = "su25.fetch_obsolete_result", FetchIn, FetchOut
    requirements = (FmExists(FETCH_FM, guide=FETCH_GUIDE, source="ZFM_RR_TC_OBS_FETCH.txt"),
                    FmAuthorized(FETCH_FM, group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, FETCH_FM, JOBNAME=data.job_name, JOBCOUNT=data.job_count)
        lines = [str(r.get("LINE", "")) for r in res.get("LISTLINES") or []]
        found = parse_lines(lines)
        path = ""
        if found and ctx.data_dir:
            folder = ctx.data_dir / "downloads" / (ctx.system_label or str(ctx.system_id))
            folder.mkdir(parents=True, exist_ok=True)
            p = folder / f"{re.sub(r'[^A-Za-z0-9._-]', '_', data.job_name)}-{data.job_count}-obsolete-tcodes.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["role", "tcode", "description", "node_id"])
                w.writeheader()
                w.writerows(found)
            path = str(p)
        return FetchOut(spool_number=str(res.get("SPOOLNUM") or ""), lines_read=len(lines), total=len(found),
                        roles=len({e["role"] for e in found}), sample=[Entry(**{k: e[k] for k in ("role", "tcode")}) for e in found[:100]],
                        file_path=path)
