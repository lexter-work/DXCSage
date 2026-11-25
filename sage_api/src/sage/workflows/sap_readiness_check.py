"""SAP Readiness Check: check notes, schedule RC_COLLECT_ANALYSIS_DATA, wait for the job, download the ZIP.
Durable: one long-held run that survives restarts. Uploading the ZIP to SAP is manual."""
from pydantic import BaseModel

from sage.runtime.errors import WaitTimeout, WorkflowFailed
from sage.sap.requirements import SettingPresent, TableReadable
from sage.tasks.rc_fetch_archive import FetchArchive, FetchArchiveIn
from sage.tasks.rc_notes_download import NotesDownload, NotesDownloadIn
from sage.tasks.rc_start_analysis import StartAnalysis, StartAnalysisIn
from sage.tasks.sap_job_status import JobStatus, JobStatusIn
from sage.tasks.sap_read_table import ReadTable, ReadTableIn
from sage.workflows.base import SettingSpec, SystemInput, Workflow

PROGRAM = "RC_COLLECT_ANALYSIS_DATA"
pad = lambda n: n.rjust(10, "0")  # noqa: E731


class ReadinessInput(SystemInput):
    variant_name: str | None = None
    job_name: str | None = None


class NoteState(BaseModel):
    number: str
    conditional: bool = False
    present: bool = False
    implemented: bool | None = None


class ReadinessOutput(BaseModel):
    job_name: str
    job_count: str
    final_status: str
    file_path: str
    filename: str
    size_bytes: int
    notes: list[NoteState]


def _in_list(field, numbers):
    return " OR ".join(f"{field} = '{pad(n)}'" for n in numbers)


class SapReadinessCheck(Workflow):
    name = "sap_readiness_check"
    description = ("Run SAP Readiness Check data collection on a registered SAP system: verify prerequisite SAP Notes "
                   "(downloading missing ones), schedule RC_COLLECT_ANALYSIS_DATA, wait until the job finishes (can take hours), "
                   "and download the ZIP archive. Upload to SAP Readiness Check stays manual.")
    Input, Output, durable = ReadinessInput, ReadinessOutput, True
    schedulable, schedule_min_minutes = True, 1440     # starts a SAP job: at most once a day
    tasks = (ReadTable, NotesDownload, StartAnalysis, JobStatus, FetchArchive)
    extra_requirements = (
        TableReadable("CWBNTHEAD", guide="Allow reading CWBNTHEAD (SAP Notes header) for the RFC user."),
        TableReadable("CWBNTCUST", guide="Allow reading CWBNTCUST (note implementation status). Its field PRSTATUS is unverified; check in SE16."),
        TableReadable("VARID", guide="Allow reading VARID (report variants)."),
        SettingPresent("default_variant", level="warn",
                       guide="Create a variant for RC_COLLECT_ANALYSIS_DATA in SA38 and enter its name as the default variant here."),
    )
    binding_settings = (SettingSpec(key="default_variant", label="Default variant",
                                    description="Used when the user gives no variant. Must exist for RC_COLLECT_ANALYSIS_DATA.", lookup=True),)

    @classmethod
    async def setting_options(cls, key, task_ctx):
        if key != "default_variant":
            raise KeyError(key)
        r = await task_ctx.rfc.read_table(task_ctx.system_id, "VARID", ["VARIANT"], f"REPORT = '{PROGRAM}'", rows=500)
        return sorted({row["VARIANT"] for row in r.rows if row["VARIANT"]})

    async def run(self, ctx, data: ReadinessInput) -> ReadinessOutput:
        cfg = await ctx.snapshot("notes_config", lambda: ctx.task_ctx.settings.get("readiness.prerequisite_notes"))
        variant = data.variant_name or ctx.task_ctx.binding.get("default_variant")
        if not variant:
            raise WorkflowFailed("No variant given and no default variant is set up for this system.")
        notes = cfg["notes"]
        required = [n["number"] for n in notes if not n.get("conditional")]
        all_numbers = [n["number"] for n in notes]

        head = await ctx.task(ReadTable, ReadTableIn(table="CWBNTHEAD", fields=["NUMM"], where=_in_list("NUMM", all_numbers)))
        have = {row["NUMM"].lstrip("0") for row in head.rows}
        missing = [n for n in required if n not in have]
        if missing:
            await ctx.task(NotesDownload, NotesDownloadIn(notes=missing))
            poll = int(cfg["download_poll_seconds"])
            try:
                head = await ctx.wait(
                    ReadTable, ReadTableIn(table="CWBNTHEAD", fields=["NUMM"], where=_in_list("NUMM", all_numbers)),
                    until=lambda o: all(n in {r["NUMM"].lstrip("0") for r in o.rows} for n in missing),
                    backoff=[[10 ** 9, poll]], max_wait=int(cfg["download_wait_seconds"]))
            except WaitTimeout:
                raise WorkflowFailed("Required SAP Notes still missing after waiting for the download: " + ", ".join(missing))
            have = {row["NUMM"].lstrip("0") for row in head.rows}
        impl = cfg["implementation_status"]
        status = {}
        if cfg.get("require_implemented"):
            r = await ctx.task(ReadTable, ReadTableIn(table=impl["table"], fields=["NUMM", impl["field"]],
                                                      where=_in_list("NUMM", required)))
            status = {row["NUMM"].lstrip("0"): row[impl["field"]] for row in r.rows}
            not_impl = [n for n in required if status.get(n) is not None and status[n] not in impl["implemented_values"]]
            if not_impl:
                raise WorkflowFailed("Required SAP Notes downloaded but not implemented (SNOTE): " + ", ".join(not_impl))
        states = [NoteState(number=n["number"], conditional=bool(n.get("conditional")), present=n["number"] in have,
                            implemented=(status[n["number"]] in impl["implemented_values"]) if n["number"] in status else None)
                  for n in notes]

        v = await ctx.task(ReadTable, ReadTableIn(table="VARID", fields=["VARIANT"],
                                                  where=f"REPORT = '{PROGRAM}' AND VARIANT = '{variant}'"))
        if not v.rows:
            raise WorkflowFailed(f"Report variant '{variant}' does not exist for {PROGRAM} on this system.")

        job = await ctx.task(StartAnalysis, StartAnalysisIn(job_name=data.job_name or PROGRAM, variant=variant))
        final = await ctx.wait(JobStatus, JobStatusIn(job_name=job.job_name, job_count=job.job_count),
                               until=lambda o: (not o.found) or o.terminal)
        if not final.found:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} was not found on the system.")
        if final.failed:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} ended {final.status_label}. Check SM37 on the system.")
        arch = await ctx.task(FetchArchive, FetchArchiveIn(job_name=job.job_name, job_count=job.job_count))
        return ReadinessOutput(job_name=job.job_name, job_count=job.job_count, final_status=final.status_label,
                               file_path=arch.file_path, filename=arch.filename, size_bytes=arch.size_bytes, notes=states)
