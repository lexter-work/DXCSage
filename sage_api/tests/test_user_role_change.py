import pytest

from sage.sap.userrole_review import Change, clean
from sage.workflows.sap_user_role_change import SapUserRoleChange
from sage.workflows.sap_user_role_review import ReviewInput, SapUserRoleReview
from tests.test_readiness import Clock, make_ctx


def C(u, r, a="assign"):
    return Change(username=u, role=r, action=a)


def world(fake, held):
    """held: {user: [roles]}. BAPIs keep their own state, like SAP does."""
    fake.lengths.update({"USR02": {"BNAME": 12}, "AGR_USERS": {"UNAME": 12, "AGR_NAME": 30, "FROM_DAT": 8, "TO_DAT": 8}, "AGR_DEFINE": {"AGR_NAME": 30},
                         "AGR_AGRS": {"AGR_NAME": 30, "CHILD_AGR": 30}, "AGR_1251": {"AGR_NAME": 30, "OBJECT": 10, "FIELD": 10, "LOW": 40, "DELETED": 1}})
    fake.tables["USR02"] = [{"BNAME": u} for u in held]
    fake.tables["AGR_USERS"] = [{"UNAME": u, "AGR_NAME": r, "FROM_DAT": "20200101", "TO_DAT": "99991231"} for u, rs in held.items() for r in rs]
    fake.tables["AGR_DEFINE"] = [{"AGR_NAME": r} for r in ("Z_POST", "Z_PAY", "Z_PO", "Z_APPROVE", "Z_DEV", "Z_ADMIN")]
    fake.tables["AGR_AGRS"] = []
    fake.tables["AGR_1251"] = [{"AGR_NAME": r, "OBJECT": o, "FIELD": "ACTVT", "LOW": "01", "DELETED": ""} for r, o in
                               (("Z_PO", "M_BEST_BSA"), ("Z_APPROVE", "M_BEST_EKO"), ("Z_DEV", "S_DEVELOP"), ("Z_ADMIN", "S_ADMI_FCD"))]
    roles = {u: [{"AGR_NAME": r, "FROM_DAT": "20200101", "TO_DAT": "99991231"} for r in rs] for u, rs in held.items()}
    fake.functions["BAPI_USER_GET_DETAIL"] = lambda **p: {"RETURN": [], "ACTIVITYGROUPS": roles[p["USERNAME"]]}

    def assign(**p):
        roles[p["USERNAME"]] = p["ACTIVITYGROUPS"]
        return {"RETURN": []}
    fake.functions["BAPI_USER_ACTGROUPS_ASSIGN"] = assign
    fake.functions["BAPI_TRANSACTION_COMMIT"] = lambda **p: {}
    return roles


async def run(wf, db, audit, rfc, settings_store, tmp_path, changes):
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    return await wf().run(ctx, ReviewInput(system_name="TS3", changes=changes))


def test_clean_normalizes_dedupes_and_rejects():
    ok, err = clean([C("alice", "z_a"), C("ALICE", "Z_A"), C("bob", "z_b", "unassign")], 10)
    assert [(c.username, c.role) for c in ok] == [("ALICE", "Z_A"), ("BOB", "Z_B")] and not err
    assert clean([C("a", "r"), C("a", "r", "unassign")], 10)[1]
    assert clean([C("a'", "r")], 10)[1] and clean([], 10)[1] and clean([C("a", "r"), C("b", "r")], 1)[1]


async def test_clean_change_is_applied_verified_and_not_repeated_on_replay(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    roles = world(fake_rfc, {"ALICE": ["Z_POST"]})
    changes = [C("alice", "Z_PAY"), C("ALICE", "Z_POST", "unassign")]
    out = await run(SapUserRoleChange, db, audit, rfc, settings_store, tmp_path, changes)
    assert out.executed and all(r.success for r in out.results) and {r["AGR_NAME"] for r in roles["ALICE"]} == {"Z_PAY"}
    assert fake_rfc.count("BAPI_USER_ACTGROUPS_ASSIGN") == 1
    again = await run(SapUserRoleChange, db, audit, rfc, settings_store, tmp_path, changes)          # replay of the same run
    assert again.executed and fake_rfc.count("BAPI_USER_ACTGROUPS_ASSIGN") == 1                      # the write is not repeated


async def test_critical_conflict_blocks_the_write_but_the_review_shows_it(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, {"ALICE": ["Z_PO"]})
    changes = [C("ALICE", "Z_APPROVE")]
    rv = await run(SapUserRoleReview, db, audit, rfc, settings_store, tmp_path, changes)
    assert not rv.ready and rv.users[0].introduced == ["SOD-002"] and "CRITICAL" in rv.errors[0]


async def test_change_refuses_on_conflict_unknown_user_or_missing_role(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, {"ALICE": ["Z_PO"]})
    out = await run(SapUserRoleChange, db, audit, rfc, settings_store, tmp_path, [C("ALICE", "Z_APPROVE"), C("NOBODY", "Z_PAY"), C("ALICE", "Z_NOPE")])
    assert not out.executed and fake_rfc.count("BAPI_USER_ACTGROUPS_ASSIGN") == 0
    text = " ".join(out.review.errors)
    assert "NOBODY" in text and "Z_NOPE" in text


async def test_noop_changes_warn_and_write_nothing(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, {"ALICE": ["Z_POST"]})
    out = await run(SapUserRoleChange, db, audit, rfc, settings_store, tmp_path, [C("ALICE", "Z_POST"), C("ALICE", "Z_PAY", "unassign")])
    assert not out.executed and len(out.review.warnings) == 2 and fake_rfc.count("BAPI_USER_ACTGROUPS_ASSIGN") == 0
