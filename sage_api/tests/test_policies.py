import io
import zipfile

import pytest

from sage.policies import PolicyError, PolicyService, extract_text, fingerprint, request_hash
from sage.runtime.context import WorkflowContext
from sage.tasks.base import TaskContext
from sage.tasks.policy_record import RecordIn
from sage.workflows.sap_record_policy_review import SapRecordPolicyReview
from sage.workflows.sap_user_role_change import SapUserRoleChange
from sage.workflows.sap_user_role_review import ReviewInput, SapUserRoleReview
from tests.test_readiness import Clock, make_ctx
from tests.test_user_role_change import C, world

TEXT = "Nobody may hold both Z_PAY and Z_POST. Changes to finance roles need a ticket number."


@pytest.fixture
async def env(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    roles = world(fake_rfc, {"ALICE": ["Z_PO"]})
    await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())            # seeds the user, chat and run rows
    pol = PolicyService(db, audit)
    n = {"i": 10}

    async def ctx():
        n["i"] += 1                                                               # a new workflow call each time, so nothing is replayed
        await db.execute("INSERT INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(?,1,?,'x','{}','running','t')", (n["i"], f"c{n['i']}"))
        tc = TaskContext(1, rfc, settings_store, {}, tmp_path, "TS3", policies=pol, actor="alice", user_id=1)
        return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=n["i"], workflow="w", actor="alice", task_ctx=tc, backoff=[[60, 10]], max_wait=7200, clock=Clock())
    return type("Env", (), {"pol": pol, "ctx": staticmethod(ctx), "roles": roles, "fake": fake_rfc})


async def review(env, *changes, **kw):
    return await SapUserRoleReview().run(await env.ctx(), ReviewInput(system_name="TS3", changes=list(changes), **kw))


async def change(env, *changes, **kw):
    return await SapUserRoleChange().run(await env.ctx(), ReviewInput(system_name="TS3", changes=list(changes), **kw))


async def record(env, p, findings=()):
    return await SapRecordPolicyReview().run(await env.ctx(), RecordIn(policy_name=p.name, kind=p.kind, request_hash=p.request_hash, fingerprint=p.fingerprint,
                                                                       findings=[{"description": d, "role": r} for r, d in findings]))


def docx(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body>" + "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n")) + "</w:body></w:document>")
    return out.getvalue()


def test_text_extraction_and_hashes():
    assert extract_text("p.md", b"# Rule\nbe good") == "# Rule\nbe good"
    assert extract_text("p.docx", docx("Rule one\nRule &amp; two")) == "Rule one\nRule & two"
    for bad in (("p.pdf", b"x"), ("p.docx", b"not a zip")):
        with pytest.raises(PolicyError):
            extract_text(*bad)
    a = [{"role": "A", "x": 1}, {"role": "B"}]
    assert request_hash("user_role", a) == request_hash("user_role", a[::-1]) != request_hash("role_auth", a)
    assert fingerprint("a") != fingerprint("b")


async def test_a_required_policy_blocks_until_the_ai_records_a_clean_review(env):
    await env.pol.save(None, "Finance policy", TEXT, True, "admin")
    r = await review(env, C("ALICE", "Z_PAY"))
    p = r.policies[0]
    assert not r.ready and p.state == "pending" and p.text == TEXT and "POLICY REVIEW NEEDED" in r.next_step and "has not been reviewed" in r.errors[0]
    refused = await change(env, C("ALICE", "Z_PAY"))
    assert not refused.executed and env.fake.count("BAPI_USER_ACTGROUPS_ASSIGN") == 0
    rec = await record(env, p)
    assert rec.recorded
    ok = await review(env, C("ALICE", "Z_PAY"))
    assert ok.ready and ok.policies[0].state == "reviewed" and ok.policies[0].findings == [] and ok.next_step == ""
    done = await change(env, C("ALICE", "Z_PAY"))
    assert done.executed and {r["AGR_NAME"] for r in env.roles["ALICE"]} == {"Z_PO", "Z_PAY"}


async def test_findings_block_the_change_and_the_first_verdict_stands(env):
    await env.pol.save(None, "Finance policy", TEXT, True, "admin")
    p = (await review(env, C("ALICE", "Z_PAY"))).policies[0]
    await record(env, p, [("Z_PAY", "No ticket number was given.")])
    r = await review(env, C("ALICE", "Z_PAY"))
    assert not r.ready and "No ticket number was given." in " ".join(r.errors) and "Z_PAY" in " ".join(r.errors)
    assert not (await change(env, C("ALICE", "Z_PAY"))).executed
    again = await record(env, p)                                               # a later "no findings" cannot replace it
    assert not again.recorded and "already recorded" in again.message
    assert not (await review(env, C("ALICE", "Z_PAY"))).ready


async def test_a_new_request_or_an_edited_policy_needs_a_new_review(env):
    await env.pol.save(None, "Finance policy", TEXT, True, "admin")
    p = (await review(env, C("ALICE", "Z_PAY"))).policies[0]
    await record(env, p)
    assert (await review(env, C("ALICE", "Z_PAY"))).ready
    assert (await review(env, C("ALICE", "Z_POST"))).policies[0].state == "pending"                    # another request
    await env.pol.save(1, "Finance policy", TEXT + " New rule.", True, "admin")
    again = (await review(env, C("ALICE", "Z_PAY"))).policies[0]
    assert again.state == "pending" and again.fingerprint != p.fingerprint
    stale = await record(env, p)                                               # the old fingerprint is refused
    assert not stale.recorded and "changed" in stale.message


async def test_optional_policy_by_name_and_unknown_names(env):
    await env.pol.save(None, "Optional", "Be careful.", False, "admin")
    assert (await review(env, C("ALICE", "Z_PAY"))).ready                                              # not required, not asked for: no check
    r = await review(env, C("ALICE", "Z_PAY"), policy_name="optional")
    assert not r.ready and r.policies[0].name == "Optional" and r.policies[0].state == "pending"
    r = await review(env, C("ALICE", "Z_PAY"), policy_name="Nope")
    assert not r.ready and "does not exist" in " ".join(r.errors)
    rec = await SapRecordPolicyReview().run(await env.ctx(), RecordIn(policy_name="Nope", kind="user_role", request_hash="x", fingerprint="y"))
    assert not rec.recorded


async def test_clearing_reviews_asks_again_and_policy_api_is_admin_only(env, client):
    await env.pol.save(None, "Finance policy", TEXT, True, "admin")
    p = (await review(env, C("ALICE", "Z_PAY"))).policies[0]
    await record(env, p)
    assert (await review(env, C("ALICE", "Z_PAY"))).ready
    await env.pol.clear_reviews(1, "admin")
    assert not (await review(env, C("ALICE", "Z_PAY"))).ready
    assert (await client.get("/api/policies")).status_code in (401, 403)


@pytest.fixture
def app_kwargs():
    return {"workflows": {"sap_record_policy_review": SapRecordPolicyReview}}


async def test_the_recording_workflow_is_offered_to_the_model_without_any_system(client, app):
    specs = await app.state.services.agent.tool_specs()
    assert [s.name for s in specs] == ["sap_record_policy_review"]
    from tests.conftest import login_admin
    await login_admin(client)
    r = await client.post("/api/policies", json={"name": "Finance policy", "text": TEXT, "required": True})
    assert r.status_code == 200 and r.json()[0]["required"] and r.json()[0]["fingerprint"] == fingerprint(TEXT)
    assert (await client.post("/api/policies", json={"name": "finance POLICY", "text": "x"})).status_code == 400
    ex = await client.put("/api/policies/extract", params={"filename": "p.docx"}, content=docx("Line one"))
    assert ex.json() == {"text": "Line one"}
    assert (await client.delete(f"/api/policies/{r.json()[0]['id']}")).json() == {"ok": True}


async def test_role_authorization_requests_are_checked_against_policies_too(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    from sage.workflows.sap_role_auth_change import SapRoleAuthChange
    from sage.workflows.sap_role_auth_review import ReviewInput as RoleInput, SapRoleAuthReview
    from tests.test_role_auth_change import C as RC, world as role_world
    calls = role_world(fake_rfc)
    await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    pol = PolicyService(db, audit)
    await pol.save(None, "Finance policy", TEXT, True, "admin")
    n = {"i": 50}

    async def ctx():
        n["i"] += 1
        await db.execute("INSERT INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(?,1,?,'x','{}','running','t')", (n["i"], f"c{n['i']}"))
        tc = TaskContext(1, rfc, settings_store, {}, tmp_path, "TS3", policies=pol, actor="alice", user_id=1)
        return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=n["i"], workflow="w", actor="alice", task_ctx=tc, backoff=[[60, 10]], max_wait=7200, clock=Clock())

    changes = [RC("Z_PARENT", "modify", value="02", cur="03")]
    r = await SapRoleAuthReview().run(await ctx(), RoleInput(system_name="TS3", changes=changes))
    assert not r.ready and r.policies[0].state == "pending" and r.policies[0].kind == "role_auth"
    out = await SapRoleAuthChange().run(await ctx(), RoleInput(system_name="TS3", changes=changes))
    assert not out.executed and calls == []
    p = r.policies[0]
    await SapRecordPolicyReview().run(await ctx(), RecordIn(policy_name=p.name, kind=p.kind, request_hash=p.request_hash, fingerprint=p.fingerprint))
    assert (await SapRoleAuthChange().run(await ctx(), RoleInput(system_name="TS3", changes=changes))).executed
