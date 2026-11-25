"""What a task or workflow needs from a SAP system. Checks are read-only: they never call a
write or job-scheduling function module. A pass proves existence and authorization, not that it works."""
import fnmatch
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from sage.sap.rfc import RfcError, SapRfc


class CheckResult(BaseModel):
    status: str                       # pass | warn | fail | blocked
    message: str = ""
    detail: list[dict] = []           # rows of a requirement that reports a list (authorization coverage)


@dataclass
class CheckEnv:
    rfc: SapRfc
    system_id: int
    rfc_user: str
    binding: dict
    settings: Any
    ping_error: RfcError | None = None
    names: dict[str, str] = field(default_factory=dict)   # abap_object_id -> this system's name
    done: dict = field(default_factory=dict)              # (kind, key) -> CheckResult of requirements checked before this one
    ssh: Any = None                                       # SapSsh
    sid: str = ""


@dataclass(frozen=True)
class Requirement:
    key: str = ""
    guide: str = ""
    source: str | None = None         # file name under static/rfc/
    level: str = "fail"               # "warn": a failure of this requirement does not block enabling the workflow
    kind: ClassVar[str] = "base"

    async def check(self, env: CheckEnv) -> CheckResult:
        raise NotImplementedError

    def auth_rows(self, names: dict[str, str] | None = None) -> list[tuple[str, str, str]]:
        return []

    def title(self) -> str:
        return f"{self.kind}: {self.key}" if self.key else self.kind


@dataclass(frozen=True)
class Reachable(Requirement):
    kind: ClassVar[str] = "reachable"

    async def check(self, env):
        e = env.ping_error
        return CheckResult(status="fail", message=e.message) if e and e.code == "CONNECT" else CheckResult(status="pass")


@dataclass(frozen=True)
class LoginOk(Requirement):
    kind: ClassVar[str] = "login"

    async def check(self, env):
        e = env.ping_error
        if e is None:
            return CheckResult(status="pass")
        if e.code == "CONNECT":
            return CheckResult(status="blocked", message="system not reachable")
        return CheckResult(status="fail", message=e.message)


@dataclass(frozen=True)
class FmExists(Requirement):
    kind: ClassVar[str] = "fm_exists"

    async def check(self, env):
        try:
            name = env.names.get(self.key, self.key)
            r = await env.rfc.read_table(env.system_id, "TFDIR", ["FUNCNAME"], f"FUNCNAME = '{name}'", rows=1)
        except RfcError as e:
            return CheckResult(status="fail", message=f"cannot read TFDIR: {e.message}")
        return CheckResult(status="pass") if r.rows else CheckResult(status="fail", message="function module not found")

    def auth_rows(self, names=None):
        return [("S_TABU_NAM", "TABLE", "TFDIR"), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class FmAuthorized(Requirement):
    group: str = ""
    kind: ClassVar[str] = "fm_authorized"

    async def check(self, env):
        # SUSR_USER_AUTH_FOR_OBJ_GET must be remote-enabled and allowed for the account.
        try:
            res = await env.rfc.call(env.system_id, "SUSR_USER_AUTH_FOR_OBJ_GET", USER_NAME=env.rfc_user, SEL_OBJECT="S_RFC")
        except RfcError as e:
            return CheckResult(status="warn", message=f"cannot verify S_RFC ({e.code}): {e.message}")
        vals: dict[str, list[str]] = {}
        for r in res.get("VALUES", []):
            vals.setdefault(r["FIELD"].strip(), []).append(r["VON"].strip())

        def allows(field_, wanted):
            return any(fnmatch.fnmatchcase(wanted, p) for p in vals.get(field_, []))

        fm = env.names.get(self.key, self.key)
        candidates = [fm] + ([env.names.get(self.group, self.group)] if self.group else [])
        ok = allows("RFC_TYPE", "FUNC") and any(allows("RFC_NAME", n) for n in candidates) and allows("ACTVT", "16")
        return CheckResult(status="pass") if ok else CheckResult(
            status="fail", message=f"S_RFC does not cover FUNC {fm} with ACTVT 16 (heuristic check)")

    def auth_rows(self, names=None):
        n = names or {}
        rows = [("S_RFC", "RFC_TYPE", "FUNC"), ("S_RFC", "RFC_NAME", n.get(self.key, self.key)), ("S_RFC", "ACTVT", "16")]
        return rows + ([("S_RFC", "RFC_NAME", n.get(self.group, self.group))] if self.group else [])


@dataclass(frozen=True)
class TableReadable(Requirement):
    kind: ClassVar[str] = "table_readable"

    async def check(self, env):
        try:
            await env.rfc.probe_table(env.system_id, self.key)
        except RfcError as e:
            return CheckResult(status="fail", message=f"{e.code}: {e.message}")
        return CheckResult(status="pass")

    def auth_rows(self, names=None):
        return [("S_TABU_NAM", "TABLE", self.key), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class SettingPresent(Requirement):
    scope: str = "binding"            # "binding" = per-system workflow setting, "global" = settings table
    level: str = "fail"               # status when missing: fail | warn
    kind: ClassVar[str] = "setting"

    async def check(self, env):
        val = env.binding.get(self.key) if self.scope == "binding" else await env.settings.get(self.key)
        return CheckResult(status="pass") if val else CheckResult(status=self.level, message=f"setting '{self.key}' is not set")


@dataclass(frozen=True)
class SshLogin(Requirement):
    """The workflow reads files on the host of the system, so the system needs optional SSH access with a trusted host key."""
    kind: ClassVar[str] = "ssh_login"

    async def check(self, env):
        from sage.sap.ssh import SshError
        try:
            await env.ssh.test(await env.ssh.params(env.system_id))
        except SshError as e:
            return CheckResult(status="fail", message=f"{e.code}: {e.message}")
        return CheckResult(status="pass")


@dataclass(frozen=True)
class FileReadable(Requirement):
    """A file on the host (key = absolute path, {sid} is replaced by the system ID in lower or upper case as written)."""
    kind: ClassVar[str] = "file_readable"

    def path(self, sid: str) -> str:
        return self.key.replace("{SID}", sid.upper()).replace("{sid}", sid.lower())

    async def check(self, env):
        from sage.sap.ssh import SshError
        ssh_state = env.done.get(("ssh_login", ""))
        if ssh_state is not None and ssh_state.status != "pass":
            return CheckResult(status="blocked", message="SSH login does not work")
        try:
            ok = await env.ssh.file_readable(env.system_id, self.path(env.sid))
        except SshError as e:
            return CheckResult(status="fail", message=f"{e.code}: {e.message}")
        return CheckResult(status="pass") if ok else CheckResult(status="fail", message=f"{self.path(env.sid)} is missing or not readable by the SSH user")

    def title(self):
        return f"file: {self.key}"


@dataclass(frozen=True)
class DeclaredAuth(Requirement):
    """Authorization values a workflow needs that no scan can see (for example a standard report checks them inside a
    background job). Listed in the authorization table and compared by AuthCoverage; this requirement itself always passes."""
    rows: tuple[tuple[str, str, str], ...] = ()
    kind: ClassVar[str] = "auth_declared"

    async def check(self, env):
        return CheckResult(status="pass", message="Compared in the authorization check.")

    def auth_rows(self, names=None):
        return list(self.rows)

    def title(self):
        return f"Authorizations for {self.key}"


SCAN_FM = "ZFM_AUTH_REQ_LIST"        # custom RFC that lists the authorization checks inside a function module (static scan)


def _covers(values: list[tuple[str, str]], wanted: str) -> bool:
    """Does one authorization field of the account allow `wanted`? Field-level and optimistic: an
    authorization value counts if any of the account's authorizations of the object holds it."""
    for von, bis in values:
        if bis:
            if von <= wanted <= bis:
                return True
        elif fnmatch.fnmatchcase(wanted, von):
            return True
    return False


async def scan_function(rfc, system_id: int, fm: str, names: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Ask ZFM_AUTH_REQ_LIST what authorizations function module `fm` (an object ID) checks. Raises RfcError or ValueError."""
    res = await rfc.call(system_id, SCAN_FM, IV_FUNCNAME=names.get(fm, fm), IV_MODE="S",
                         IV_MAX_DEPTH=3, IV_INCL_STANDARD="", IV_TRACE_USER="")
    errs = [str(m.get("MESSAGE", "")).strip() for m in res.get("ET_RETURN") or [] if m.get("TYPE") in ("E", "A")]
    if errs:
        raise RfcError("ABAP", "; ".join(errs))
    try:
        payload = json.loads(res.get("EV_JSON") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"unreadable scan result: {e}") from e
    return payload.get("rows") or [], payload.get("unresolved") or []


@dataclass(frozen=True)
class AuthCoverage(Requirement):
    """Every authorization value the workflow needs, compared with the RFC account, all at once.

    Needed values come from the declared requirements (S_RFC, S_TABU_NAM) plus a static scan of each
    function module with ZFM_AUTH_REQ_LIST. "missing" is reliable (the value is in none of the account's
    authorizations); "granted" is optimistic because the account's values are read per field, not per
    authorization. Unverified: SUSR_USER_AUTH_FOR_OBJ_GET remote-enabled and returning FIELD/VON/BIS.
    """
    fms: tuple[str, ...] = ()
    static: tuple[Requirement, ...] = ()
    kind: ClassVar[str] = "auth_coverage"

    async def check(self, env):
        need: dict[tuple[str, str, str], set[str]] = {}

        def add(obj, fld, val, by):
            if obj and "DUMMY" not in val.upper():
                need.setdefault((obj, fld, val), set()).add(by)

        for r in self.static:
            for o, f, v in r.auth_rows(env.names):
                add(o, f, v, r.key or r.kind)
        unresolved, scan_error = [], None
        for fm in self.fms:
            try:
                scanned, unres = await scan_function(env.rfc, env.system_id, fm, env.names)
            except (RfcError, ValueError) as e:
                scan_error = getattr(e, "message", None) or str(e)
                break
            for row in scanned:
                add(str(row.get("auth_object", "")), str(row.get("auth_field", "")), str(row.get("auth_values", "")), fm)
            unresolved += [f"{fm}: {u}" for u in unres]

        tables = [t for (k, t) in env.done if k == "table_readable"]
        tables_ok = bool(tables) and all(env.done[("table_readable", t)].status == "pass" for t in tables)
        cache: dict[str, dict | None] = {}

        async def account(obj):
            if obj not in cache:
                try:
                    res = await env.rfc.call(env.system_id, "SUSR_USER_AUTH_FOR_OBJ_GET", USER_NAME=env.rfc_user, SEL_OBJECT=obj)
                except RfcError:
                    cache[obj] = None
                else:
                    vals: dict[str, list[tuple[str, str]]] = {}
                    for r in res.get("VALUES", []):
                        vals.setdefault(r["FIELD"].strip(), []).append((r["VON"].strip(), (r.get("BIS") or "").strip()))
                    cache[obj] = vals
            return cache[obj]

        rows = []
        for (o, f, v), by in sorted(need.items()):
            if o == "S_TABU_NAM" and tables_ok:
                status, note = "granted", "proved by the table read test"
            elif "<" in v:
                status, note = "review", "the value is decided at run time"
            else:
                vals = await account(o)
                if vals is None:
                    status, note = "unknown", "the account's authorizations could not be read"
                else:
                    status, note = ("granted", "") if _covers(vals.get(f, []), v) else ("missing", "")
            rows.append({"object": o, "field": f, "value": v, "status": status, "source": ", ".join(sorted(by)), "note": note})
        rows += [{"object": "", "field": "", "value": u, "status": "review", "source": "", "note": "not followed by the scan"} for u in unresolved]

        n = Counter(r["status"] for r in rows if r["object"])
        review = n["review"] + n["unknown"]
        msg = f"{n['missing']} missing, {review} to review, {n['granted']} granted of {sum(n.values())} authorization values"
        if scan_error:
            msg += f". The authorizations checked inside the function modules are not listed: {scan_error}"
        elif unresolved:
            msg += f". {len(unresolved)} call(s) were not followed by the scan"
        status = "fail" if n["missing"] else "warn" if (review or scan_error or unresolved) else "pass"
        return CheckResult(status=status, message=msg, detail=rows)
