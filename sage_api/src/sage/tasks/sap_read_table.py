from pydantic import BaseModel

from sage.tasks.base import Task


class ReadTableIn(BaseModel):
    table: str
    fields: list[str]
    where: str = ""
    rows: int | None = None


class ReadTableOut(BaseModel):
    rows: list[dict[str, str]]
    truncated: bool


class ReadTable(Task):
    """Generic read through RFC_READ_TABLE. The calling workflow declares TableReadable for each table it reads."""
    name, Input, Output = "sap.read_table", ReadTableIn, ReadTableOut

    async def run(self, ctx, data):
        r = await ctx.rfc.read_table(ctx.system_id, data.table, data.fields, data.where, data.rows)
        return ReadTableOut(rows=r.rows, truncated=r.truncated)
