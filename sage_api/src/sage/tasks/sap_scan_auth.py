from pydantic import BaseModel

from sage.sap.requirements import SCAN_FM, FmAuthorized, FmExists, scan_function
from sage.sap.rfc import RfcError
from sage.tasks.base import Task

GUIDE = "Create ZFM_AUTH_REQ_LIST (remote-enabled) as in the attached source. It lists the authorizations a function module checks."


class ScanAuthIn(BaseModel):
    function_module: str      # abap_object_id


class AuthRow(BaseModel):
    auth_object: str
    auth_field: str
    auth_values: str
    source: str = ""
    callee_path: str = ""


class ScanAuthOut(BaseModel):
    rows: list[AuthRow] = []
    unresolved: list[str] = []
    error: str = ""           # set when the scan could not run; the caller reports it instead of failing the whole run


class ScanAuth(Task):
    """Read-only. Lists every authorization one custom function module checks, following its calls."""
    name, Input, Output = "sap.scan_auth", ScanAuthIn, ScanAuthOut
    requirements = (FmExists(SCAN_FM, guide=GUIDE, source="ZFM_AUTH_REQ_LIST.txt"),
                    FmAuthorized(SCAN_FM, group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        names = await ctx.rfc.names(ctx.system_id)
        try:
            rows, unresolved = await scan_function(ctx.rfc, ctx.system_id, data.function_module, names)
        except (RfcError, ValueError) as e:
            return ScanAuthOut(error=getattr(e, "message", None) or str(e))
        return ScanAuthOut(rows=[AuthRow(**{k: str(r.get(k, "")) for k in AuthRow.model_fields}) for r in rows], unresolved=unresolved)
