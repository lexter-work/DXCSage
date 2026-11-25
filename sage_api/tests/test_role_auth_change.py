import pytest

from sage.sap.rfc import RfcError
from sage.sap.roleauth_review import RoleChange, clean
from sage.workflows.sap_role_auth_change import SapRoleAuthChange
from sage.workflows.sap_role_auth_review import ReviewInput, SapRoleAuthReview
from tests.test_readiness import Clock, make_ctx


def C(role, action, obj="F_BKPF_BUK", field="ACTVT", value="01", cur=""):
    return RoleChange(role=role, action=action, object=obj, field=field, value=value, current_value=cur)


def row(role, obj, field, low):
    return {"AGR_NAME": role, "OBJECT": obj, "FIELD": field, "LOW": low, "DELETED": ""}


def world(fake):
    fake.lengths.update({"AGR_DEFINE": {"AGR_NAME": 30, "PARENT_AGR": 30}, "AGR_AGRS": {"AGR_NAME": 30, "CHILD_AGR": 30},
                         "AGR_TCODES": {"AGR_NAME": 30, "TCODE": 20}, "AGR_1251": {"AGR_NAME": 30, "OBJECT": 10, "FIELD": 10, "LOW": 40, "DELETED": 1}})
    fake.tables["AGR_DEFINE"] = [{"AGR_NAME": "Z_PARENT", "PARENT_AGR": ""}, {"AGR_NAME": "Z_CHILD", "PARENT_AGR": "Z_PARENT"},
                                 {"AGR_NAME": "Z_B", "PARENT_AGR": ""}, {"AGR_NAME": "SAP_ALL_X", "PARENT_AGR": ""}, {"AGR_NAME": "Z_COMP", "PARENT_AGR": ""}]
    fake.tables["AGR_AGRS"] = [{"AGR_NAME": "Z_COMP", "CHILD_AGR": "Z_B"}]
    fake.tables["AGR_TCODES"] = [{"AGR_NAME": "Z_B", "TCODE": "SE16"}]
    fake.tables["AGR_1251"] = [row("Z_PARENT", "F_BKPF_BUK", "ACTVT", "03"), row("Z_PARENT", "F_BKPF_BES", "ACTVT", "03"),
                               row("Z_PARENT", "S_TCODE", "TCD", "SE16"), row("Z_B", "F_BKPF_BUK", "ACTVT", "03"), row("SAP_ALL_X", "F_BKPF_BUK", "ACTVT", "03")]
    calls = []
    fake.functions["ZFM_RR_ROLE_AUTH_CHANGE"] = lambda **p: calls.append(("change", p["ACTIVITY_GROUP"])) or {"RETURN": []}
    fake.functions["ZFM_RR_TCODE_REMOVE"] = lambda **p: calls.append(("tcode", p["IV_ROLE_NAME"], p["IV_TCODE"])) or {"EV_RETURN_TYPE": "S", "EV_RETURN_MSG": "removed", "EV_REMOVED_COUNT": 2}
    fake.functions["ZFM_RR_DERIVED_REGENERATE"] = lambda **p: calls.append(("derived", p["IV_ROLE_NAME"])) or {"EV_RETURN_TYPE": "S", "EV_RETURN_MSG": "ok"}
    return calls


async def run(wf, db, audit, rfc, settings_store, tmp_path, changes):
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    return await wf().run(ctx, ReviewInput(system_name="TS3", changes=changes))


def test_clean_rejects_quotes_bad_modify_and_add_remove_clash():
    assert clean([C("z", "add", value="x' OR 1=1")], 10)[1]
    assert clean([C("z", "modify", value="01", cur="01")], 10)[1]
    assert clean([C("z", "add"), C("z", "remove")], 10)[1]
    ok, err = clean([C("z_a", "add"), C("Z_A", "add")], 10)
    assert len(ok) == 1 and not err


async def test_modify_remove_tcode_and_derived_regeneration_then_replay_does_not_repeat(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = world(fake_rfc)
    changes = [C("Z_PARENT", "modify", value="02", cur="03"), RoleChange(role="Z_PARENT", action="remove_tcode", value="se16")]
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, changes)
    assert out.executed and calls == [("change", "Z_PARENT"), ("tcode", "Z_PARENT", "SE16"), ("derived", "Z_PARENT")]
    sent = next(p for f, p in fake_rfc.calls if f == "ZFM_RR_ROLE_AUTH_CHANGE")
    assert sent["AUTHORIZATION_VALUES"] == [{"OBJECT": "F_BKPF_BUK", "FIELD": "ACTVT", "LOW": "02", "HIGH": ""}]
    assert sent["AUTHORIZATION_VALUES_DELETE"][0]["LOW"] == "03"
    await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, changes)                 # replay
    assert len(calls) == 3


async def test_policy_and_role_problems_block_every_write(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = world(fake_rfc)
    bad = [C("Z_PARENT", "add", obj="S_DEVELOP", value="03"), C("SAP_ALL_X", "modify", value="02", cur="03"), C("Z_CHILD", "add"),
           C("Z_COMP", "add"), C("Z_NONE", "add"), C("Z_B", "remove", value="99"), C("Z_B", "modify", value="*", cur="03")]
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, bad)
    text = " ".join(out.review.errors)
    assert not out.executed and calls == []
    for needle in ("derived role of Z_PARENT", "composite", "Z_NONE does not exist", "does not have the value 99", "policy violation"):
        assert needle in text
    assert {v.policy for v in out.review.violations} >= {"Restricted authorization object", "SAP standard role protection", "Wildcard value"}


async def test_new_critical_conflict_blocks_but_review_reports_it(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = world(fake_rfc)
    await settings_store.set("sod.matrix", {"conflicts": [{"id": "X-1", "object_1": "F_BKPF_BUK", "activity_1": "01,02", "object_2": "F_BKPF_BES",
                                                           "risk_level": "CRITICAL", "description": "post and approve"}]}, "t")
    rv = await run(SapRoleAuthReview, db, audit, rfc, settings_store, tmp_path, [C("Z_PARENT", "modify", value="01", cur="03")])
    assert not rv.ready and rv.roles[0].introduced == ["X-1"] and "CRITICAL" in " ".join(rv.errors)
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, [C("Z_PARENT", "modify", value="01", cur="03")])
    assert not out.executed and calls == []


async def test_failed_role_stops_the_run_and_skips_regeneration(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = world(fake_rfc)

    def boom(**p):
        raise RfcError("VALUE_NOT_FOUND", "no such value")
    fake_rfc.functions["ZFM_RR_ROLE_AUTH_CHANGE"] = boom
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path,
                    [C("Z_B", "modify", value="02", cur="03"), C("Z_PARENT", "modify", value="02", cur="03")])
    assert out.executed and [d.success for d in out.changes_applied] == [False] and "not changed" in out.changes_applied[0].message
    assert out.derived_regenerated == [] and calls == [] and "STOPPED" in out.message


def org_world(fake):
    calls = world(fake)
    fake.lengths["AGR_1252"] = {"AGR_NAME": 30, "VARBL": 10, "LOW": 40}
    fake.tables["AGR_1252"] = [{"AGR_NAME": "Z_PARENT", "VARBL": "BUKRS", "LOW": "1000"}, {"AGR_NAME": "Z_B", "VARBL": "BUKRS", "LOW": "1000"}]
    fake.functions["ZFM_RR_ORG_LEVEL_CHANGE"] = lambda **p: calls.append(("org", p["ACTIVITY_GROUP"], len(p["ORG_VALUES"]), len(p["ORG_VALUES_DELETE"]))) or {"RETURN": []}
    return calls


def O(role, action, level="$BUKRS", value="2000", cur=""):
    return RoleChange(role=role, action=action, object="F_IGNORED", field=level, value=value, current_value=cur)


def test_org_level_changes_drop_the_object_and_need_a_level_name():
    ok, err = clean([O("z_a", "add")], 10)
    assert ok[0].object == "" and ok[0].field == "$BUKRS" and not err
    assert clean([O("z_a", "add", level="$")], 10)[1]


async def test_org_level_review_checks_the_values_on_the_role(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = org_world(fake_rfc)
    bad = [O("Z_PARENT", "add", value="1000"), O("Z_PARENT", "remove", value="9999"), O("Z_PARENT", "add", level="$KOKRS"), O("Z_B", "modify", value="*", cur="1000")]
    rv = await run(SapRoleAuthReview, db, audit, rfc, settings_store, tmp_path, bad)
    text = " ".join(rv.errors)
    assert not rv.ready and "already has the value 1000" in text and "does not have the value 9999" in text and "no organization level $KOKRS" in text
    assert {v.policy for v in rv.violations} == {"Wildcard value"}
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, bad)
    assert not out.executed and calls == []


async def test_org_level_change_calls_its_own_module_and_skips_derived_regeneration(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = org_world(fake_rfc)
    out = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, [O("Z_PARENT", "add"), O("Z_PARENT", "modify", value="3000", cur="1000")])
    assert out.executed and calls == [("org", "Z_PARENT", 2, 1)] and out.derived_regenerated == []
    assert any("derived roles" in w for w in out.review.warnings)
    sent = next(p for f, p in fake_rfc.calls if f == "ZFM_RR_ORG_LEVEL_CHANGE")
    assert sent["ORG_VALUES"] == [{"VARBL": "BUKRS", "LOW": "2000", "HIGH": ""}, {"VARBL": "BUKRS", "LOW": "3000", "HIGH": ""}] and sent["ORG_VALUES_DELETE"][0]["LOW"] == "1000"


async def test_org_and_authorization_changes_in_one_request_regenerate_derived_roles(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = org_world(fake_rfc)
    mixed = await run(SapRoleAuthChange, db, audit, rfc, settings_store, tmp_path, [C("Z_PARENT", "modify", value="02", cur="03"), O("Z_PARENT", "add", value="4000")])
    assert [c[0] for c in calls] == ["change", "org", "derived"] and mixed.executed
