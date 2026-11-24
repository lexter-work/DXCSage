"""What a task or workflow needs from a SAP system. Checks are read-only: they never call a
write or job-scheduling function module. A pass proves existence and authorization, not that it works."""
import fnmatch
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel

from sage.sap.rfc import RfcError, SapRfc


class CheckResult(BaseModel):
    status: str                       # pass | warn | fail | blocked
    message: str = ""


@dataclass
class CheckEnv:
    rfc: SapRfc
    system_id: int
    rfc_user: str
    binding: dict
    settings: Any
    ping_error: RfcError | None = None


@dataclass(frozen=True)
class Requirement:
    key: str = ""
    guide: str = ""
    source: str | None = None         # file name under static/rfc/
    kind: ClassVar[str] = "base"

    async def check(self, env: CheckEnv) -> CheckResult:
        raise NotImplementedError

    def auth_rows(self) -> list[tuple[str, str, str]]:
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
            r = await env.rfc.read_table(env.system_id, "TFDIR", ["FUNCNAME"], f"FUNCNAME = '{self.key}'", rows=1)
        except RfcError as e:
            return CheckResult(status="fail", message=f"cannot read TFDIR: {e.message}")
        return CheckResult(status="pass") if r.rows else CheckResult(status="fail", message="function module not found")

    def auth_rows(self):
        return [("S_TABU_NAM", "TABLE", "TFDIR"), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class FmAuthorized(Requirement):
    group: str = ""
    kind: ClassVar[str] = "fm_authorized"

    async def check(self, env):
        # Unverified: SUSR_USER_AUTH_FOR_OBJ_GET must be remote-enabled and allowed for the account.
        try:
            res = await env.rfc.call(env.system_id, "SUSR_USER_AUTH_FOR_OBJ_GET", USER_NAME=env.rfc_user, SAP_OBJECT="S_RFC")
        except RfcError as e:
            return CheckResult(status="warn", message=f"cannot verify S_RFC ({e.code}): {e.message}")
        vals: dict[str, list[str]] = {}
        for r in res.get("VALUES", []):
            vals.setdefault(r["FIELD"].strip(), []).append(r["VON"].strip())

        def allows(field_, wanted):
            return any(fnmatch.fnmatchcase(wanted, p) for p in vals.get(field_, []))

        names = [self.key] + ([self.group] if self.group else [])
        ok = allows("RFC_TYPE", "FUNC") and any(allows("RFC_NAME", n) for n in names) and allows("ACTVT", "16")
        return CheckResult(status="pass") if ok else CheckResult(
            status="fail", message=f"S_RFC does not cover FUNC {self.key} with ACTVT 16 (heuristic check)")

    def auth_rows(self):
        rows = [("S_RFC", "RFC_TYPE", "FUNC"), ("S_RFC", "RFC_NAME", self.key), ("S_RFC", "ACTVT", "16")]
        return rows + ([("S_RFC", "RFC_NAME", self.group)] if self.group else [])


@dataclass(frozen=True)
class TableReadable(Requirement):
    kind: ClassVar[str] = "table_readable"

    async def check(self, env):
        try:
            await env.rfc.probe_table(env.system_id, self.key)
        except RfcError as e:
            return CheckResult(status="fail", message=f"{e.code}: {e.message}")
        return CheckResult(status="pass")

    def auth_rows(self):
        return [("S_TABU_NAM", "TABLE", self.key), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class SettingPresent(Requirement):
    scope: str = "binding"            # "binding" = per-system workflow setting, "global" = settings table
    level: str = "fail"               # status when missing: fail | warn
    kind: ClassVar[str] = "setting"

    async def check(self, env):
        val = env.binding.get(self.key) if self.scope == "binding" else await env.settings.get(self.key)
        return CheckResult(status="pass") if val else CheckResult(status=self.level, message=f"setting '{self.key}' is not set")
