import io

import pytest
from openpyxl import Workbook, load_workbook

from sage.providers.base import Done, ToolUse
from sage.sap.excel_requests import KINDS, build_template, parse
from sage.uploads import UploadError, UploadService
from sage.workflows.sap_role_auth_review import ReviewInput as RoleInput, SapRoleAuthReview
from sage.workflows.sap_user_role_review import ReviewInput as UserInput, SapUserRoleReview
from tests.conftest import login_admin
from tests.test_readiness import Clock, make_ctx
from tests.test_user_role_change import C, world


def book(headers, rows, title="Request"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(headers)
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_template_is_valid_and_uploading_it_untouched_changes_nothing(kind):
    data = build_template(kind)
    assert load_workbook(io.BytesIO(data)).sheetnames == ["Request", "Examples", "Instructions"]
    r = parse(data)
    assert r["kind"] == kind and r["rows"] == [] and r["errors"] == []               # the samples are on their own sheet


def test_user_roles_rows_synonyms_and_row_errors():
    r = parse(book(["Username", "Role", "Action"], [["jsmith", "z_a", "Grant"], ["jsmith", "z_b", "revoke"], [None, None, None], ["x", "y", "fly"], ["x", None, "assign"]]))
    assert r["kind"] == "user_roles" and r["rows"] == [{"username": "JSMITH", "role": "Z_A", "action": "assign"}, {"username": "JSMITH", "role": "Z_B", "action": "unassign"}]
    assert len(r["errors"]) == 2 and r["errors"][0].startswith("Row 5")


def test_role_auth_actions_are_worked_out_and_actvt_is_padded():
    r = parse(book(["Role", "Object", "Field", "Current Value", "Requested Value", "Action"],
                   [["z_fi", "f_bkpf_buk", "actvt", 3, 2, None], ["z_fi", "f_bkpf_buk", "bukrs", None, "1000", ""], ["z_fi", "f_bkpf_buk", "bukrs", "2000", None, None],
                    ["z_fi", "f_bkpf_buk", "$KOKRS", None, "1000", None], ["z_fi", "f_bkpf_buk", "bukrs", None, None, "add"], ["z_fi", None, "bukrs", None, "1", "add"]]))
    assert r["kind"] == "role_auth"
    assert r["rows"][0] == {"role": "Z_FI", "action": "modify", "object": "F_BKPF_BUK", "field": "ACTVT", "value": "02", "current_value": "03"}
    assert r["rows"][2]["value"] == "2000"
    assert [x["action"] for x in r["rows"]] == ["modify", "add", "remove", "add"] and r["rows"][3] == {"role": "Z_FI", "action": "add", "object": "", "field": "$KOKRS", "value": "1000", "current_value": ""}
    assert any("add needs" in e for e in r["errors"]) and any("Row 7" in e and "Object" in e for e in r["errors"])


def test_tcode_layout_accepts_the_csv_of_the_obsolete_tcode_scan_and_bad_files_are_reported():
    r = parse(book(["role", "tcode", "description", "node_id"], [["z_basis", "su01", "x", "3"]]))
    assert r["kind"] == "tcode_removal" and r["rows"][0]["action"] == "remove_tcode" and r["rows"][0]["value"] == "SU01"
    assert parse(book(["a", "b"], [[1, 2]]))["kind"] is None and "not a readable" in parse(b"PK nope")["errors"][0]


async def test_upload_api_validates_and_a_file_is_attached_to_the_run_text(client, app):
    await login_admin(client)
    cid = (await client.post("/api/chats", json={"title": "t", "provider": "anthropic", "model": "claude-sonnet-5-5"}))
    await app.state.services.settings.set("providers.anthropic_api_key", "k", "t")
    cid = (await client.post("/api/chats", json={"title": "t", "provider": "anthropic", "model": "claude-sonnet-5-5"})).json()["id"]
    put = lambda name, body: client.put(f"/api/chats/{cid}/uploads", params={"filename": name}, content=body)  # noqa: E731
    assert (await put("a.txt", b"x")).status_code == 400 and (await put("a.xlsx", b"not a zip")).status_code == 400
    assert (await put("a.xlsx", b"PK" + b"0" * 6_000_000)).status_code == 400
    ok = (await put("../../req uest.xlsx", book(["Username", "Role", "Action"], [["a", "r", "assign"]]))).json()
    assert ok["kind"] == "user_roles" and ok["rows"] == 1 and "/" not in ok["filename"]
    assert (await client.put("/api/chats/999/uploads", params={"filename": "a.xlsx"}, content=b"PK")).status_code == 404
    assert (await client.get("/api/templates/user_roles.xlsx")).status_code == 200 and (await client.get("/api/templates/zzz.xlsx")).status_code == 404
    run = (await client.post(f"/api/chats/{cid}/runs", json={"text": "review this", "files": [ok["id"]]})).json()["run_id"]
    msg = (await client.get(f"/api/chats/{cid}/messages")).json()[0]["content"]
    assert ok["id"] in msg and "user_roles, 1 row(s)" in msg and run
    assert (await client.post(f"/api/chats/{cid}/runs", json={"text": "x", "files": ["nope"]})).status_code in (404, 409)


async def test_workflow_reads_the_file_a_user_attached_and_only_that_users_file(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, {"ALICE": ["Z_PO"]})
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    up = UploadService(db, audit, tmp_path)
    ctx.task_ctx.uploads, ctx.task_ctx.user_id = up, 1
    saved = await up.save({"id": 1, "username": "u"}, 1, "r.xlsx", book(["Username", "Role", "Action"], [["alice", "z_pay", "assign"]]))
    rv = await SapUserRoleReview().run(ctx, UserInput(system_name="TS3", file_id=saved["id"]))
    assert rv.ready and [(c.username, c.role) for c in rv.changes] == [("ALICE", "Z_PAY")]
    both = await SapUserRoleReview().run(ctx, UserInput(system_name="TS3", file_id=saved["id"], changes=[C("ALICE", "Z_PAY")]))
    assert not both.ready and "not both" in both.errors[0]
    ctx.task_ctx.user_id = 2                                                                  # somebody else asks for the same file id
    with pytest.raises(UploadError):
        await up.read(saved["id"], 2)


async def test_wrong_layout_for_the_workflow_is_refused_with_a_clear_message(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, {"ALICE": ["Z_PO"]})
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    up = UploadService(db, audit, tmp_path)
    ctx.task_ctx.uploads, ctx.task_ctx.user_id = up, 1
    saved = await up.save({"id": 1, "username": "u"}, 1, "r.xlsx", book(["Username", "Role", "Action"], [["alice", "z_pay", "assign"]]))
    rv = await SapRoleAuthReview().run(ctx, RoleInput(system_name="TS3", file_id=saved["id"]))
    assert not rv.ready and "user_roles" in rv.errors[0]
