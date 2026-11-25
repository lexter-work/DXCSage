"""Facts and a Basis work order for removing add-ons from a SAP system. Read-only: nothing on SAP changes.
Reads CVERS, PAT03, PAT08, SEOCLASS and TADIR through RFC_READ_TABLE."""
from collections import Counter

from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.addon import PATCH_TYPES, current_patch, normalize, risk, work_order
from sage.sap.requirements import TableReadable
from sage.tasks.sap_read_table import ReadTable, ReadTableIn
from sage.workflows.base import SystemInput, Workflow

MAX_COMPONENTS = 10


class AddonInput(SystemInput):
    components: list[str]


class ComponentReport(BaseModel):
    component: str
    category: str                    # not_installed | protected | uninstallable | not_uninstallable
    release: str = ""
    current_patch: str = ""
    deinstall_plugin: str = ""
    objects_total: int = 0
    objects_by_type: dict[str, int] = {}
    custom_objects: int = 0
    custom_sample: list[str] = []
    objects_truncated: bool = False
    risk: str = ""
    risk_factors: list[str] = []
    reason: str
    work_order: str = ""


class AddonOutput(BaseModel):
    system: str
    components: list[ComponentReport]
    note: str


def _any(field, values):
    return " OR ".join(f"{field} = '{v}'" for v in values)


class SapAddonUninstallGuide(Workflow):
    name = "sap_addon_uninstall_guide"
    description = ("For up to 10 software components (add-ons) of a registered SAP system, report whether SAINT allows the "
                   "uninstall (PAT08), the deinstallation plugin class, how many repository objects and custom objects the "
                   "component's packages hold, and a risk level, and write a Basis work order (Maintenance Planner + /SAINT). "
                   "Read-only: nothing is uninstalled. Dependencies between components are not determined.")
    Input, Output = AddonInput, AddonOutput
    tasks = (ReadTable,)
    extra_requirements = tuple(TableReadable(t, guide=f"Allow reading {t} for the RFC user.") for t in ("CVERS", "PAT03", "PAT08", "SEOCLASS", "TADIR"))

    async def run(self, ctx, data: AddonInput) -> AddonOutput:
        try:
            wanted = sorted({normalize(c) for c in data.components})
        except ValueError as e:
            raise WorkflowFailed(str(e)) from e
        if not wanted or len(wanted) > MAX_COMPONENTS:
            raise WorkflowFailed(f"Give between 1 and {MAX_COMPONENTS} components.")

        async def protected():
            return [c.upper() for c in await ctx.task_ctx.settings.get("addon.protected_components")]
        prot = set(await ctx.snapshot("protected", protected))

        cv = await ctx.task(ReadTable, ReadTableIn(table="CVERS", fields=["COMPONENT", "RELEASE"], where="RELEASE <> 'DEV'"))
        installed = {r["COMPONENT"].strip().upper(): r["RELEASE"].strip() for r in cv.rows if r["COMPONENT"].strip()}
        targets = [c for c in wanted if c in installed and c not in prot]

        patches, allowed, plugins = {}, set(), set()
        if targets:
            types = _any("PATCH_TYPE", PATCH_TYPES)
            p3 = await ctx.task(ReadTable, ReadTableIn(table="PAT03", fields=["COMPONENT", "COMP_REL", "PATCH", "TO_REL"],
                                                       where=f"STATUS <> 'N' AND ( {types} ) AND ( {_any('COMPONENT', targets)} )"))
            for c in targets:
                patches[c] = current_patch([r for r in p3.rows if r["COMPONENT"].strip().upper() == c], installed[c])
            ps = sorted({p for p in patches.values() if p})
            if ps:
                p8 = await ctx.task(ReadTable, ReadTableIn(table="PAT08", fields=["PATCH"],
                                                           where=f"X_ATTRIB = 'DEINSTALL_ALLOWED' AND FLAG = ' ' AND ( {_any('PATCH', ps)} )"))
                allowed = {r["PATCH"].strip() for r in p8.rows}
            names = [f"CL_{c}_DEINSTALL_PLUGIN" for c in targets]
            sc = await ctx.task(ReadTable, ReadTableIn(table="SEOCLASS", fields=["CLSNAME"], where=_any("CLSNAME", names)))
            plugins = {r["CLSNAME"].strip() for r in sc.rows}

        sid = ctx.task_ctx.system_label
        out = []
        for c in wanted:
            if c not in installed:
                out.append(ComponentReport(component=c, category="not_installed", reason="Not in CVERS (not installed, or only a local DEV registration)."))
                continue
            if c in prot:
                out.append(ComponentReport(component=c, category="protected", release=installed[c],
                                           reason="Protected core component (setting addon.protected_components). It cannot be uninstalled."))
                continue
            td = await ctx.task(ReadTable, ReadTableIn(table="TADIR", fields=["OBJECT", "OBJ_NAME"], where=f"DEVCLASS LIKE '{c}%'"))
            objs = [(r["OBJECT"].strip(), r["OBJ_NAME"].strip()) for r in td.rows if r["OBJ_NAME"].strip() and r["OBJECT"].strip() != "DEVC"]
            custom = [f"{o}:{n}" for o, n in objs if n.upper().startswith(("Z", "Y"))]
            level, factors = risk(len(custom))
            ok = bool(patches[c]) and patches[c] in allowed
            reason = ("SAINT allows the uninstall of the current patch (PAT08 DEINSTALL_ALLOWED)." if ok else
                      "The current patch is not marked deinstall-allowed in PAT08." if patches[c] else
                      "No current patch found in PAT03, so the uninstall check could not be made.")
            if td.truncated:
                factors.append("The object list was cut at the row cap, so the counts are a minimum.")
            out.append(ComponentReport(
                component=c, category="uninstallable" if ok else "not_uninstallable", release=installed[c], current_patch=patches[c],
                deinstall_plugin=f"CL_{c}_DEINSTALL_PLUGIN" if f"CL_{c}_DEINSTALL_PLUGIN" in plugins else "",
                objects_total=len(objs), objects_by_type=dict(Counter(o for o, _ in objs)), custom_objects=len(custom),
                custom_sample=custom[:20], objects_truncated=td.truncated, risk=level, risk_factors=factors, reason=reason,
                work_order=work_order(c, sid, installed[c], patches[c], ok, level, factors, len(custom))))
        return AddonOutput(system=sid, components=out, note=(
            "Facts only. Dependencies between components are not read from the system, so check them in Maintenance Planner. "
            "Open transports are not checked. A custom object count looks at packages that start with the component name."))
