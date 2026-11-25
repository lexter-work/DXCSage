import pytest

from sage.runtime.errors import WorkflowFailed
from sage.sap.addon import current_patch, normalize, risk
from sage.workflows.sap_addon_uninstall_guide import AddonInput, Classification, SapAddonUninstallGuide
from tests.test_readiness import Clock, make_ctx


def test_helpers():
    assert normalize(" gbx01hr5 ") == "GBX01HR5"
    with pytest.raises(ValueError):
        normalize("X' OR 1=1")
    rows = [{"COMP_REL": "100", "PATCH": "A", "TO_REL": "100"}, {"COMP_REL": "100", "PATCH": "B", "TO_REL": "100"},
            {"COMP_REL": "200", "PATCH": "Z", "TO_REL": "200"}]
    assert current_patch(rows, "100") == "B" and current_patch(rows, "300") == ""
    assert [risk(n)[0] for n in (0, 11, 51)] == ["LOW", "MEDIUM", "HIGH"]


def world(fake):
    L = {"CVERS": {"COMPONENT": 30, "RELEASE": 10}, "PAT03": {"COMPONENT": 30, "COMP_REL": 10, "PATCH": 20, "TO_REL": 10, "STATUS": 1, "PATCH_TYPE": 3},
         "PAT08": {"PATCH": 20, "X_ATTRIB": 30, "FLAG": 1}, "SEOCLASS": {"CLSNAME": 30}, "TADIR": {"OBJECT": 4, "OBJ_NAME": 40, "DEVCLASS": 30}}
    fake.lengths.update(L)
    fake.tables["CVERS"] = [{"COMPONENT": c, "RELEASE": r} for c, r in (("SAP_BASIS", "758"), ("GBX01HR5", "100"), ("PERSONAS", "300"), ("HOME", "DEV"))]
    fake.tables["PAT03"] = [{"COMPONENT": "GBX01HR5", "COMP_REL": "100", "PATCH": "P1", "TO_REL": "100", "STATUS": "I", "PATCH_TYPE": "AOI"},
                            {"COMPONENT": "PERSONAS", "COMP_REL": "300", "PATCH": "P2", "TO_REL": "300", "STATUS": "I", "PATCH_TYPE": "AOI"},
                            {"COMPONENT": "PERSONAS", "COMP_REL": "300", "PATCH": "OLD", "TO_REL": "300", "STATUS": "N", "PATCH_TYPE": "AOI"}]
    fake.tables["PAT08"] = [{"PATCH": "P1", "X_ATTRIB": "DEINSTALL_ALLOWED", "FLAG": ""}]
    fake.tables["SEOCLASS"] = [{"CLSNAME": "CL_GBX01HR5_DEINSTALL_PLUGIN"}]
    fake.tables["TADIR"] = ([{"OBJECT": "DEVC", "OBJ_NAME": "GBX01HR5", "DEVCLASS": "GBX01HR5"}]
                            + [{"OBJECT": "TABL", "OBJ_NAME": f"ZT{i}", "DEVCLASS": "GBX01HR5"} for i in range(12)]
                            + [{"OBJECT": "PROG", "OBJ_NAME": "STD", "DEVCLASS": "GBX01HR5_X"}])


async def run(db, audit, rfc, settings_store, tmp_path, comps):
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    return await SapAddonUninstallGuide().run(ctx, AddonInput(system_name="TS3", components=comps))


async def test_categories_objects_risk_and_work_order(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)
    out = await run(db, audit, rfc, settings_store, tmp_path, ["gbx01hr5", "PERSONAS", "SAP_BASIS", "HOME", "NOPE"])
    by = {c.component: c for c in out.components}
    assert {k: v.category for k, v in by.items()} == {"GBX01HR5": "uninstallable", "PERSONAS": "not_uninstallable", "SAP_BASIS": "protected",
                                                      "HOME": "not_installed", "NOPE": "not_installed"}
    g = by["GBX01HR5"]
    assert (g.current_patch, g.deinstall_plugin, g.objects_total, g.custom_objects, g.risk) == ("P1", "CL_GBX01HR5_DEINSTALL_PLUGIN", 13, 12, "MEDIUM")
    assert g.objects_by_type == {"TABL": 12, "PROG": 1} and "/SAINT" in g.work_order and "GBX01HR5" in g.work_order
    assert by["PERSONAS"].work_order and "not marked deinstall-allowed" in by["PERSONAS"].reason      # old patch row (STATUS N) ignored
    assert by["SAP_BASIS"].work_order == "" and by["HOME"].work_order == ""


async def test_bad_input_refused(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)
    for bad in ([], ["A'B"], [f"C{i}" for i in range(11)]):
        with pytest.raises(WorkflowFailed):
            await run(db, audit, rfc, settings_store, tmp_path, bad)


def deps(fake):
    fake.lengths["CVERS_REF"] = {"COMPONENT": 30, "RELEASE": 10, "EXT_COMPONENT": 30, "EXT_RELEASE": 10}
    fake.tables["CVERS_REF"] = [{"COMPONENT": "PERSONAS", "RELEASE": "300", "EXT_COMPONENT": "GBX01HR5", "EXT_RELEASE": "100"},
                                {"COMPONENT": "GBX01HR5", "RELEASE": "100", "EXT_COMPONENT": "SAP_BASIS", "EXT_RELEASE": "750"},
                                {"COMPONENT": "NOTINSTALLED", "RELEASE": "1", "EXT_COMPONENT": "GBX01HR5", "EXT_RELEASE": "100"}]


async def test_dependencies_raise_risk_and_are_in_the_work_order(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)
    deps(fake_rfc)
    g = (await run(db, audit, rfc, settings_store, tmp_path, ["GBX01HR5"])).components[0]
    assert g.dependencies_checked and g.required_by == ["PERSONAS"] and g.requires == ["SAP_BASIS"] and g.risk == "HIGH"
    assert "PERSONAS" in g.work_order and "must be removed or kept compatible first" in g.work_order


async def test_unreadable_dependency_table_is_reported_not_fatal(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)                                                   # no CVERS_REF in the fake: the read fails
    out = await run(db, audit, rfc, settings_store, tmp_path, ["GBX01HR5"])
    g = out.components[0]
    assert not g.dependencies_checked and g.risk == "MEDIUM" and "could NOT be read" in g.work_order and "could not be read" in out.note


async def test_the_model_is_asked_to_classify(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)
    out = await run(db, audit, rfc, settings_store, tmp_path, ["GBX01HR5", "SAP_BASIS"])
    assert "CLASSIFICATION NEEDED for: GBX01HR5." in out.next_step and "your judgment, not a fact" in out.next_step      # the protected SAP_BASIS is not asked


async def test_a_classification_is_shown_and_only_raises_the_risk(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc)
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    cl = [Classification(component="gbx01hr5", category="sap_core", reason="Looks like a base component.")]
    out = await SapAddonUninstallGuide().run(ctx, AddonInput(system_name="TS3", components=["GBX01HR5"], classifications=cl))
    g = out.components[0]
    assert out.next_step == "" and g.risk == "HIGH" and g.classification.category == "sap_core" and any("AI judgment" in f for f in g.risk_factors)
    assert "Classification (AI judgment, not a fact)" in g.work_order and "Looks like a base component." in g.work_order and g.category == "uninstallable"


def test_category_changes_risk_but_never_lowers_it():
    assert risk(0, [], "sap_core")[0] == "HIGH" and risk(0, [], "industry_solution")[0] == "MEDIUM" and risk(0, [], "partner_or_customer")[0] == "LOW"
    assert risk(60, [], "sap_optional")[0] == "HIGH" and risk(11, [], "unknown")[0] == "MEDIUM"
