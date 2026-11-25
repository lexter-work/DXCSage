import pytest

from sage.runtime.errors import WorkflowFailed
from sage.sap.sod import conflicts_for_roles, normalize_rules
from sage.settings_store import DEFAULTS
from sage.workflows.sap_user_sod_check import SapUserSodCheck, SodInput
from tests.test_readiness import Clock, make_ctx


def data(objects=(), tcodes=(), acts=None):
    return {"objects": set(objects), "tcodes": set(tcodes), "activities": acts or {}}


def test_conflict_can_span_roles_and_activity_scopes_a_side():
    rules = normalize_rules(DEFAULTS["sod.matrix"])
    roles = ["Z_POST", "Z_PAY"]
    ok = conflicts_for_roles(rules, roles, {"Z_POST": data(["F_BKPF_BUK"], acts={"F_BKPF_BUK": {"01"}}), "Z_PAY": data(["F_BKPF_BES"])})
    assert [(c["rule_id"], c["roles"]) for c in ok] == [("SOD-001", ["Z_PAY", "Z_POST"])]
    display = conflicts_for_roles(rules, roles, {"Z_POST": data(["F_BKPF_BUK"], acts={"F_BKPF_BUK": {"03"}}), "Z_PAY": data(["F_BKPF_BES"])})
    assert display == []                                               # display-only posting is not a conflict


def test_most_severe_first_and_bad_rules_rejected():
    rules = normalize_rules(DEFAULTS["sod.matrix"])
    both = conflicts_for_roles(rules, ["R"], {"R": data(["F_BKPF_BUK", "F_BKPF_BES", "S_DEVELOP", "S_ADMI_FCD"])})
    assert [c["severity"] for c in both] == ["CRITICAL", "HIGH"]
    for bad in ({}, {"conflicts": [{"id": "X", "object_1": "A"}]}, {"conflicts": [{"id": "X", "object_1": "A'", "object_2": "B"}]}):
        with pytest.raises(ValueError):
            normalize_rules(bad)


def world(fake, assigned, grants, composite=()):
    fake.lengths.update({"USR02": {"BNAME": 12}, "AGR_USERS": {"AGR_NAME": 30, "FROM_DAT": 8, "TO_DAT": 8, "UNAME": 12},
                         "AGR_AGRS": {"AGR_NAME": 30, "CHILD_AGR": 30}, "AGR_1251": {"OBJECT": 10, "FIELD": 10, "LOW": 40, "AGR_NAME": 30, "DELETED": 1}})
    fake.tables["USR02"] = [{"BNAME": "ALICE"}]
    fake.tables["AGR_USERS"] = assigned
    fake.tables["AGR_AGRS"] = [{"AGR_NAME": c, "CHILD_AGR": k} for c, k in composite]
    fake.tables["AGR_1251"] = grants


async def run(db, audit, rfc, settings_store, tmp_path, user="alice"):
    ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, Clock())
    return await SapUserSodCheck().run(ctx, SodInput(system_name="TS3", username=user))


def asg(role, frm="20200101", to="99991231"):
    return {"AGR_NAME": role, "UNAME": "ALICE", "FROM_DAT": frm, "TO_DAT": to}


async def test_expired_assignment_ignored_composite_expanded_and_conflict_found(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, [asg("Z_COMP"), asg("Z_OLD", to="20210101")], composite=[("Z_COMP", "Z_A"), ("Z_COMP", "Z_B")],
          grants=[{"AGR_NAME": "Z_A", "OBJECT": "M_BEST_BSA", "FIELD": "ACTVT", "LOW": "01"},
                  {"AGR_NAME": "Z_B", "OBJECT": "M_BEST_EKO", "FIELD": "ACTVT", "LOW": "01"},
                  {"AGR_NAME": "Z_OLD", "OBJECT": "S_DEVELOP", "FIELD": "ACTVT", "LOW": "02"}])
    out = await run(db, audit, rfc, settings_store, tmp_path)
    assert out.roles_checked == ["Z_A", "Z_B", "Z_COMP"] and out.has_critical
    assert [c.rule_id for c in out.conflicts] == ["SOD-002"] and out.unverified_roles == []


async def test_unknown_user_no_roles_and_unsafe_name(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, [], [])
    out = await run(db, audit, rfc, settings_store, tmp_path)
    assert out.user_exists and out.total_conflicts == 0 and "no currently valid role" in out.message


async def test_unknown_user_reported(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, [], [])
    fake_rfc.tables["USR02"] = []
    assert (await run(db, audit, rfc, settings_store, tmp_path)).user_exists is False


async def test_unsafe_username_refused(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    with pytest.raises(WorkflowFailed):
        await run(db, audit, rfc, settings_store, tmp_path, user="A' OR 1=1")
