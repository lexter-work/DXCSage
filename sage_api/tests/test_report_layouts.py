import io
import json
import logging

import pytest
from openpyxl import load_workbook

from sage.reports import build
from sage.reports.layouts import LAYOUTS
from sage.workflows.registry import discover

META = {"workflow": "w", "call_id": 7, "run_id": 3, "status": "ok", "system": "Test (TS3, client 100)", "requested_by": "alice",
        "started_at": "2026-11-25T10:00:00Z", "ended_at": "2026-11-25T10:01:00Z"}
CONF = {"rule_id": "X-1", "severity": "CRITICAL", "roles": ["Z_A", "Z_B"], "conflicting_objects": "F_A / F_B", "rule_description": "post and approve", "recommendation": "split"}
LOW = {**CONF, "rule_id": "X-2", "severity": "LOW"}
POLICY = {"name": "Finance", "state": "pending", "fingerprint": "f", "request_hash": "h", "kind": "user_role", "text": "t", "findings": []}
USER_REVIEW = {"ready": False, "errors": ["e1"], "warnings": ["w1"], "next_step": "do it", "unverified_roles": ["Z_B"], "policies": [POLICY],
               "changes": [{"username": "ALICE", "role": "Z_A", "action": "assign"}, {"username": "BOB", "role": "Z_B", "action": "unassign"}],
               "users": [{"username": "ALICE", "roles_now": ["Z_PO"], "roles_after": ["Z_PO", "Z_A"], "conflicts_now": ["X-2"], "conflicts_after": [LOW, CONF], "introduced": ["X-1"]},
                         {"username": "BOB", "roles_now": ["Z_B"], "roles_after": [], "conflicts_now": [], "conflicts_after": [], "introduced": []}]}
ROLE_REVIEW = {"ready": False, "errors": ["e1"], "warnings": [], "next_step": "", "unverified_roles": [], "policies": [],
               "violations": [{"role": "Z_A", "object": "S_DEVELOP", "policy": "Restricted authorization object", "description": "no"}],
               "changes": [{"role": "Z_A", "action": "modify", "object": "F_BKPF_BUK", "field": "ACTVT", "value": "02", "current_value": "03"},
                           {"role": "Z_A", "action": "add", "object": "", "field": "$BUKRS", "value": "2000", "current_value": ""},
                           {"role": "Z_A", "action": "remove_tcode", "object": "S_TCODE", "field": "TCD", "value": "SE16", "current_value": ""}],
               "roles": [{"role": "Z_A", "derived_children": ["Z_A_1"], "conflicts_now": [], "conflicts_after": [CONF], "introduced": ["X-1"]}]}
SAMPLES = {
    "sap_readiness_check": {"job_name": "RC", "job_count": "1", "final_status": "Finished", "file_path": "/f/a.zip", "filename": "a.zip", "size_bytes": 2048, "notes": [
        {"number": "1", "conditional": False, "present": True, "implemented": True}, {"number": "2", "conditional": False, "present": True, "implemented": False},
        {"number": "3", "conditional": True, "present": False, "implemented": None}]},
    "sap_obsolete_tcodes": {"job_name": "J", "job_count": "2", "total": 150, "roles": 2, "file_path": "/f/o.txt", "note": "",
                            "sample": [{"role": "Z_A", "tcode": "SU01"}, {"role": "Z_A", "tcode": "SE16"}, {"role": "Z_B", "tcode": "SM30"}]},
    "sap_auth_requirements": {"system": "TS3", "workflows": [
        {"workflow": "w1", "values": [{"object": "S_RFC", "field": "RFC_NAME", "value": "X", "source": "declared"}], "unresolved": ["u"], "errors": []},
        {"workflow": "w2", "values": [{"object": "S_RFC", "field": "RFC_NAME", "value": "X", "source": "declared"}], "unresolved": [], "errors": ["boom"]}]},
    "sap_user_sod_check": {"username": "ALICE", "user_exists": True, "roles_checked": ["Z_A", "Z_B"], "unverified_roles": ["Z_B"], "total_conflicts": 2, "has_critical": True,
                           "conflicts": [LOW, CONF], "message": "m"},
    "sap_addon_uninstall_guide": {"system": "TS3", "note": "n", "next_step": "classify", "components": [
        {"component": "GBX", "category": "uninstallable", "release": "100", "current_patch": "P1", "deinstall_plugin": "CL_X", "objects_total": 13, "objects_by_type": {"TABL": 12, "PROG": 1},
         "custom_objects": 12, "custom_sample": ["TABL:ZT1"], "required_by": ["PERSONAS"], "requires": ["SAP_BASIS"], "dependencies_checked": True,
         "classification": {"component": "GBX", "category": "sap_core", "confidence": "high", "reason": "base"}, "risk": "HIGH", "risk_factors": ["a", "b"], "reason": "ok",
         "work_order": "LINE 1\nLINE 2"}, {"component": "SAP_BASIS", "category": "protected", "release": "758", "reason": "core"}]},
    "sap_user_role_review": USER_REVIEW,
    "sap_user_role_change": {"executed": True, "review": {**USER_REVIEW, "ready": True, "errors": []}, "message": "Changed SAP.",
                             "results": [{"role": "Z_A", "action": "assign", "success": True, "note": "verified"}, {"role": "Z_B", "action": "unassign", "success": False, "note": "still there"}]},
    "sap_role_auth_review": ROLE_REVIEW,
    "sap_role_auth_change": {"executed": True, "review": {**ROLE_REVIEW, "ready": True, "errors": []}, "message": "Changed SAP.",
                             "changes_applied": [{"role": "Z_A", "success": True, "message": "Changed Z_A"}],
                             "tcode_results": [{"role": "Z_A", "tcode": "SE16", "success": False, "return_type": "E", "message": "locked", "removed_values": 0}],
                             "derived_regenerated": [{"role": "Z_A", "success": True, "message": "ok"}]},
    "sap_sum_status": {"system": "TS3", "state": "ERROR", "phase": "EXTRACTION", "phase_detail": "d", "progress_pct": 41.5, "eta": None, "time_remaining": None, "message": "m",
                       "source": "SUMOBSERVER.XML", "required_action": "Fix it",
                       "diagnosis": {"error_code": "E1", "category": "c", "severity": "HIGH", "root_cause": "rc", "recommended_fix": "rf", "sap_note": "1", "auto_recoverable": False, "matched_text": "t"},
                       "raw_error_context": "line a\nline b"},
    "sap_record_policy_review": {"recorded": True, "message": "Recorded 1 finding(s)."},
}
INPUTS = {"sap_record_policy_review": {"policy_name": "Finance", "kind": "user_role", "request_hash": "h", "fingerprint": "f", "findings": [{"role": "Z_A", "description": "no ticket"}]}}


def make(name, caplog):
    wf = discover()[name]
    data = wf.Output.model_validate(SAMPLES[name]).model_dump(mode="json")          # the real model: a field added later breaks this test
    with caplog.at_level(logging.ERROR, logger="sage.reports"):
        raw = build(name, {**META, "workflow": name}, INPUTS.get(name, {"system_name": "TS3"}), json.dumps(data))
    assert not caplog.records, "the layout failed and the generic report was used"
    wb = load_workbook(io.BytesIO(raw))
    return wb, {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}


def facts(s):
    return {r[0]: r[1] for r in s["Summary"] if r[0]}


def test_every_workflow_has_a_layout_and_a_sample():
    assert set(discover()) == set(LAYOUTS) == set(SAMPLES)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_layout_runs_and_shows_every_field_of_the_result(name, caplog):
    wb, s = make(name, caplog)
    assert wb.sheetnames[0] == "Summary" and "Input" in wb.sheetnames
    assert "Other values" not in {r[0] for r in s["Summary"]} and "Other values" not in wb.sheetnames           # no field was left out of the layout
    assert facts(s)["Target system"] == "Test (TS3, client 100)" and s["Summary"][0][0] == LAYOUTS[name][0]


def test_review_layouts(caplog):
    _, s = make("sap_user_role_review", caplog)
    f = facts(s)
    assert f["Verdict"] == "Not ready" and f["New conflicts introduced"] == 1 and f["Roles not fully read"] == "Z_B" and "1 not reviewed yet" in f["Written policies"]
    assert s["Changes"][1] == ["ALICE", "Z_A", "Assign"] and s["Users"][1][3] == "Z_A" and s["Users"][2][4] == "Z_B"
    assert [r[1:4] for r in s["Conflicts after"][1:3]] == [["X-1", "CRITICAL", "NEW"], ["X-2", "LOW", "Existing"]]                      # worst first, new marked
    assert s["Policies"][1][:2] == ["Finance", "PENDING"] and ["Error", "e1"] in s["Findings"] and "Execution" not in s
    _, s = make("sap_role_auth_review", caplog)
    assert facts(s)["Policy violations"] == 1 and s["Changes"][2][3] == "Organization level $BUKRS" and s["Changes"][1][4:6] == ["03", "02"]
    assert s["Policy violations"][1][2] == "Restricted authorization object" and s["Roles"][1][1] == "Z_A_1"


def test_change_layouts_show_what_was_done(caplog):
    _, s = make("sap_user_role_change", caplog)
    assert facts(s)["Verdict"] == "Applied to SAP" and facts(s)["Verified after the change"] == "1 of 2"
    assert s["Changes"][0][3:] == ["Result", "Note"] and s["Changes"][1][3] == "OK" and s["Changes"][2][3:] == ["FAILED", "still there"]
    _, s = make("sap_role_auth_change", caplog)
    assert facts(s)["Steps that failed"] == 1
    assert [r[6] for r in s["Changes"][1:]] == ["OK", "OK", "FAILED"] and s["Changes"][3][7] == "locked"
    assert [r[0] for r in s["Execution"][1:]] == ["Authorization values", "Transaction code removal", "Derived role regeneration"]


def test_status_and_report_layouts(caplog):
    _, s = make("sap_sum_status", caplog)
    f = facts(s)
    assert f["State"] == "ERROR" and f["Progress"] == "42%" and f["Expected end"] == "unknown" and s["Diagnosis"][1] == ["Error code", "E1"] and s["Error context"][2][0] == "line b"
    _, s = make("sap_readiness_check", caplog)
    assert facts(s)["Required SAP Notes"] == "1 of 2 in place" and [r[4] for r in s["SAP Notes"][1:]] == ["IMPLEMENTED", "NOT IMPLEMENTED", "REVIEW"]
    _, s = make("sap_obsolete_tcodes", caplog)
    assert s["By role"][1] == ["Z_A", 2] and s["Removal request"][0] == ["Role", "Tcode"] and any("first 3 of 150" in str(r) for r in s["Summary"])
    _, s = make("sap_auth_requirements", caplog)
    assert s["To request"][1] == ["S_RFC", "RFC_NAME", "X", "w1, w2"] and s["Not resolved"][1] == ["w1", "u"] and s["Errors"][1] == ["w2", "boom"]
    _, s = make("sap_user_sod_check", caplog)
    assert facts(s)["Critical conflict"] == "Yes" and s["Conflicts"][1][:2] == ["X-1", "CRITICAL"] and s["Roles checked"][2] == ["Z_B", "No"]


def test_addon_layout_has_a_work_order_sheet_per_component(caplog):
    wb, s = make("sap_addon_uninstall_guide", caplog)
    assert facts(s)["Uninstallable"] == 1 and facts(s)["High risk"] == "GBX" and "Work order GBX" in wb.sheetnames and "Work order SAP_BASIS" not in wb.sheetnames
    assert s["Work order GBX"][1:] == [["LINE 1"], ["LINE 2"]] and s["Components"][1][11] == "SAP core or technical base" and s["Objects by type"][1] == ["GBX", "PROG", 1]


def test_policy_record_and_failed_calls(caplog):
    _, s = make("sap_record_policy_review", caplog)
    assert facts(s)["Policy"] == "Finance" and s["Findings"][1] == ["Z_A", "no ticket"]
    raw = build("sap_user_role_change", {**META, "status": "error"}, {}, "Invalid input: x")                           # a failed call uses the generic report
    assert {r[0]: r[1] for r in load_workbook(io.BytesIO(raw))["Summary"].iter_rows(values_only=True) if r[0]}["Error"] == "Invalid input: x"
    raw = build("sap_unknown_workflow", META, {}, json.dumps({"a": 1}))                                                   # no layout: the generic report
    assert load_workbook(io.BytesIO(raw)).sheetnames == ["Summary", "Input"]
