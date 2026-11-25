"""Facts and a Basis work order for removing add-ons from a SAP system. Read-only: nothing on SAP changes.
Reads CVERS, PAT03, PAT08, SEOCLASS and TADIR through RFC_READ_TABLE."""
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from sage.runtime.errors import WorkflowFailed
from sage.sap.addon import CATEGORIES, DEP_FIELDS, DEP_TABLE, PATCH_TYPES, current_patch, dependents, normalize, risk, work_order
from sage.sap.rfc import RfcError
from sage.sap.requirements import TableReadable
from sage.tasks.sap_read_table import ReadTable, ReadTableIn
from sage.workflows.base import SystemInput, Workflow

MAX_COMPONENTS = 10


class Classification(BaseModel):
    component: str
    category: Literal["sap_core", "industry_solution", "sap_optional", "partner_or_customer", "unknown"]
    confidence: Literal["high", "medium", "low"] = "medium"
    reason: str = Field("", max_length=300)


class AddonInput(SystemInput):
    components: list[str]
    classifications: list[Classification] = []      # the model's own judgment, given on a second call (see next_step)


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
    required_by: list[str] = []         # installed components that require this one
    requires: list[str] = []
    dependencies_checked: bool = False
    classification: Classification | None = None
    objects_truncated: bool = False
    risk: str = ""
    risk_factors: list[str] = []
    reason: str
    work_order: str = ""


class AddonOutput(BaseModel):
    system: str
    components: list[ComponentReport]
    note: str
    next_step: str = ""


def _any(field, values):
    return " OR ".join(f"{field} = '{v}'" for v in values)


class SapAddonUninstallGuide(Workflow):
    name = "sap_addon_uninstall_guide"
    description = ("For up to 10 software components (add-ons) of a registered SAP system, report whether SAINT allows the "
                   "uninstall (PAT08), the deinstallation plugin class, how many repository objects and custom objects the "
                   "component's packages hold, which installed components require it, and a risk level, and write a Basis work order "
                   "(Maintenance Planner + /SAINT). Read-only: nothing is uninstalled. The first call asks you to classify each installed "
                   "component from the evidence; call it again with `classifications` to put your judgment into the risk and the work order.")
    schedulable = True
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

        patches, allowed, plugins, deps, checked = {}, set(), set(), [], False
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
            try:                                    # the table and its fields are not verified on a system: a failure only means no dependency facts
                dr = await ctx.task(ReadTable, ReadTableIn(table=DEP_TABLE, fields=DEP_FIELDS, where=f"( {_any('EXT_COMPONENT', targets)} ) OR ( {_any('COMPONENT', targets)} )"))
                deps, checked = dr.rows, not dr.truncated
            except RfcError:
                pass
        given = {c.component.strip().upper(): c for c in data.classifications}

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
            by, needs = dependents(deps, c, installed) if checked else ([], [])
            cls = given.get(c)
            level, factors = risk(len(custom), by, cls.category if cls else "")
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
                required_by=by, requires=needs, dependencies_checked=checked, classification=cls,
                work_order=work_order(c, sid, installed[c], patches[c], ok, level, factors, len(custom), checked, by, needs,
                                      cls.category if cls else "", cls.reason if cls else "")))
        open_ = [r.component for r in out if r.category in ("uninstallable", "not_uninstallable") and r.classification is None]
        step = ("CLASSIFICATION NEEDED for: " + ", ".join(open_) + ". From the evidence in `components` (component name, release, object types, custom object sample, "
                "installed components that require it) judge for each one a category: " + "; ".join(f"{k} = {v}" for k, v in CATEGORIES.items()) +
                ". Give a confidence (high, medium, low) and a reason of one sentence. If the evidence is not enough, use unknown. Then call this workflow again with the "
                "same components and a `classifications` list. Say clearly to the user that the category is your judgment, not a fact from the system.") if open_ else ""
        return AddonOutput(system=sid, components=out, next_step=step, note=(
            ("Dependencies come from " + DEP_TABLE + " and are a help, not the final answer: Maintenance Planner calculates them." if checked else
             "Dependencies could not be read from this system (" + DEP_TABLE + " is not readable, or its fields differ), so check them in Maintenance Planner. ") +
            " A category is the model's judgment and can only raise the risk. Open transports are not checked. A custom object count looks at packages that start with the component name."))
