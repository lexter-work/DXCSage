from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from sage.sap.requirements import SCAN_FM, AuthCoverage, FmAuthorized, FmExists, LoginOk, Reachable, Requirement
from sage.tasks.base import Task


class SystemInput(BaseModel):
    system_name: str


class SettingSpec(BaseModel):
    key: str
    label: str
    required: bool = False
    description: str = ""
    lookup: bool = False     # the UI can list valid values from the system (see Workflow.setting_options)


class Workflow(ABC):
    """The tool the model calls once. Runs fixed steps by calling shared tasks."""
    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    durable: ClassVar[bool] = False
    tasks: ClassVar[tuple[type[Task], ...]] = ()
    extra_requirements: ClassVar[tuple[Requirement, ...]] = ()
    binding_settings: ClassVar[tuple[SettingSpec, ...]] = ()
    schedulable: ClassVar[bool] = False                # True only for read-only workflows that may run unattended on a schedule
    result_states: ClassVar[tuple[str, ...]] = ()      # states of the result an email rule may react to (see result_state)

    @classmethod
    def result_state(cls, output) -> str | None:
        """The state the result is in (one of result_states), or None. Lets a status workflow send mail on ERROR and so on."""
        return None

    @classmethod
    def requirements(cls) -> list[Requirement]:
        seen, out = set(), []

        def unique(items):
            for r in items:
                if (r.kind, r.key) not in seen:
                    seen.add((r.kind, r.key))
                    out.append(r)

        unique((Reachable(), LoginOk(), *[r for t in cls.tasks for r in t.requirements], *cls.extra_requirements))
        fms = tuple(r.key for r in out if r.kind == "fm_exists")
        # Listing every authorization up front needs ZFM_AUTH_REQ_LIST. Without it the check degrades to a warning.
        unique((FmExists(SCAN_FM, level="warn", source="ZFM_AUTH_REQ_LIST.txt",
                         guide="Optional but recommended: create ZFM_AUTH_REQ_LIST (remote-enabled) as in the attached source. It lets Sage list every authorization a function module needs, so you can request them all at once."),
                FmAuthorized(SCAN_FM, group="ZFG_MCPARCHPH", level="warn")))
        unique((AuthCoverage(fms=fms, static=tuple(out)),))
        return out

    @classmethod
    def abap_objects(cls) -> list[tuple[str, str]]:
        """(abap_object_id, kind) of every custom ABAP object this workflow needs. IDs are fixed; each system may name them differently."""
        out: dict[str, str] = {}
        for r in cls.requirements():
            if r.kind in ("fm_exists", "fm_authorized") and r.key[:1] in ("Z", "Y", "/"):      # custom objects only, not standard SAP modules
                out.setdefault(r.key, "function_module")
            if getattr(r, "group", ""):
                out.setdefault(r.group, "function_group")
        return list(out.items())

    @classmethod
    async def setting_options(cls, key: str, task_ctx) -> list[str]:
        """Valid values for a binding setting whose SettingSpec has lookup=True. Read-only SAP reads only."""
        raise NotImplementedError(key)

    @abstractmethod
    async def run(self, ctx, data: BaseModel) -> BaseModel: ...


def all_abap_objects(workflows) -> dict[str, str]:
    """abap_object_id -> kind, across every workflow."""
    return {oid: kind for wf in workflows.values() for oid, kind in wf.abap_objects()}
