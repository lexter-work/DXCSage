import io
import json

from openpyxl import load_workbook

from sage.report import build_report
from tests.conftest import login_admin

META = {"workflow": "sap_addon_uninstall_guide", "call_id": 7, "run_id": 3, "status": "ok", "system": "Test (TS3, client 100)",
        "requested_by": "alice", "started_at": "2026-11-25T10:00:00Z", "ended_at": "2026-11-25T10:01:00Z"}
OUT = {"system": "TS3", "executed": True, "note": "=HYPERLINK(\"http://x\")",
       "components": [{"component": "A", "risk": "LOW", "risk_factors": ["one", "two"], "objects_by_type": {"TABL": 2}}, {"component": "B", "custom_sample": ["Z1"]}],
       "review": {"ready": False, "errors": ["bad"], "roles": [{"role": "Z_A", "introduced": []}]}}


def sheets(data):
    wb = load_workbook(io.BytesIO(data))
    return wb, {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}


def test_every_part_of_a_result_gets_a_sheet_and_text_never_runs_as_a_formula():
    wb, s = sheets(build_report(META, {"system_name": "TS3", "components": ["A", "B"]}, json.dumps(OUT)))
    assert wb.sheetnames[:2] == ["Summary", "Input"] and "components" in wb.sheetnames and "review" in wb.sheetnames and "review roles" in wb.sheetnames
    summary = dict((r[0], r[1]) for r in s["Summary"] if r[0])
    assert summary["Status"] == "Completed" and summary["Requested by"] == "alice" and summary["Executed"] == "Yes" and summary["Target system"] == "Test (TS3, client 100)"
    assert wb["Summary"]["B" + str([r[0] for r in s["Summary"]].index("Note") + 1)].data_type == "s"        # stored as text, not a formula
    assert s["components"][0] == ["Component", "Risk", "Risk factors", "Objects by type", "Custom sample"]
    assert s["components"][1][2] == "one; two" and s["components"][2][4] == "Z1" and "TABL" in s["components"][1][3]
    assert s["Input"][0] == ["System name", "TS3"] and s["Input"][1] == ["Components", "A; B"]


DEEP = {"ready": False, "roles": [
    {"role": "Z_A", "conflicts_after": [{"rule_id": "X-1", "severity": "CRITICAL", "objects": ["F_A", "F_B"]}, {"rule_id": "X-2", "severity": "HIGH", "objects": []}]},
    {"role": "Z_B", "conflicts_after": [{"rule_id": "X-3", "severity": "HIGH", "objects": ["F_C"]}], "derived": {"children": [{"name": "Z_B_1"}]}}]}


def test_nested_parts_keep_their_parent_at_any_depth():
    _, s = sheets(build_report(META, {}, json.dumps({"review": DEEP})))
    assert s["review roles"][0] == ["Row", "Role"] and s["review roles"][1:] == [[1, "Z_A"], [2, "Z_B"]]
    c = s["review roles conflicts_after"]
    assert c[0] == ["Parent row", "Parent", "Rule id", "Severity", "Objects"]
    assert c[1:] == [[1, "Z_A", "X-1", "CRITICAL", "F_A; F_B"], [1, "Z_A", "X-2", "HIGH", None], [2, "Z_B", "X-3", "HIGH", "F_C"]]      # one sheet for all parents
    d = s["review roles derived children"]
    assert d[0] == ["Parent row", "Parent", "Name"] and d[1] == [2, "Z_B", "Z_B_1"]
    assert not any("{" in str(v) for sheet in s.values() for row in sheet for v in row)                         # no JSON left in a cell


def test_a_failed_call_and_an_unreadable_output_still_give_a_report():
    _, s = sheets(build_report({**META, "status": "error"}, {}, "Invalid input: field required"))
    rows = {r[0]: r[1] for r in s["Summary"] if r[0]}
    assert rows["Status"] == "Failed" and rows["Error"] == "Invalid input: field required" and s["Input"] == [["Input", "none"]]
    _, s = sheets(build_report(META, {}, None))
    assert "Executed" not in {r[0] for r in s["Summary"]}


async def test_report_download_checks_the_owner_and_the_call_state(client, app):
    await login_admin(client)
    db = app.state.services.db
    me = (await db.fetchone("SELECT id FROM users WHERE username='admin'"))["id"]
    other = await db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('bob','x','user','t')")
    for uid, rid, cid, st in ((me, 1, 1, "ok"), (me, 1, 2, "waiting"), (other, 2, 3, "ok")):
        await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(?,?,'c','p','m','t')", (rid, uid))
        await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(?,?,?,'p','m','done','t')", (rid, rid, uid))
        await db.execute("INSERT INTO tool_calls(id,run_id,provider_call_id,workflow,input,output,status,started_at) VALUES(?,?,?,?,?,?,?,'t')",
                         (cid, rid, f"c{cid}", "sap_sum_status", "{}", json.dumps({"state": "OK"}), st))
    r = await client.get("/api/tool-calls/1/report.xlsx")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and "sage-sap-sum-status-1.xlsx" in r.headers["content-disposition"]
    assert load_workbook(io.BytesIO(r.content)).sheetnames[0] == "Summary"
    assert (await client.get("/api/tool-calls/2/report.xlsx")).status_code == 409                 # still waiting
    assert (await client.get("/api/tool-calls/3/report.xlsx")).status_code == 200                 # an admin may read any run
    assert (await client.get("/api/tool-calls/99/report.xlsx")).status_code == 404
    client.cookies.clear()
    assert (await client.get("/api/tool-calls/1/report.xlsx")).status_code in (401, 403)
