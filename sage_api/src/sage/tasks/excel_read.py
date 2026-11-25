from pydantic import BaseModel

from sage.sap.excel_requests import parse
from sage.tasks.base import Task
from sage.uploads import UploadError


class ReadIn(BaseModel):
    file_id: str
    expect: list[str]            # the layouts this workflow accepts


class ReadOut(BaseModel):
    kind: str | None
    rows: list[dict]
    errors: list[str]


class ReadRequestFile(Task):
    """Reads an Excel change request the user attached to the chat. No SAP access. Stored like every task, so a replay reads the same rows."""
    name, Input, Output = "excel.read_request", ReadIn, ReadOut

    async def run(self, ctx, data):
        try:
            parsed = parse(await ctx.uploads.read(data.file_id, ctx.user_id))
        except UploadError as e:
            return ReadOut(kind=None, rows=[], errors=[str(e)])
        if parsed["kind"] and parsed["kind"] not in data.expect:
            return ReadOut(kind=parsed["kind"], rows=[], errors=[f"This file is a '{parsed['kind']}' request, but this workflow takes: {', '.join(data.expect)}."])
        return ReadOut(**parsed)
