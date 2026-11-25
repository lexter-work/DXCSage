"""Where the changes of a change request come from: the list the model fills in from the chat, or an Excel file the user attached."""
from sage.tasks.excel_read import ReadIn, ReadRequestFile


async def request_changes(ctx, changes, file_id, expect: list[str], convert):
    """(changes, errors). Give changes or file_id, not both."""
    if file_id and changes:
        return [], ["Give the changes either in the list or as an Excel file, not both."]
    if file_id:
        out = await ctx.task(ReadRequestFile, ReadIn(file_id=file_id, expect=expect))
        return [convert(r) for r in out.rows], out.errors
    return list(changes), []
