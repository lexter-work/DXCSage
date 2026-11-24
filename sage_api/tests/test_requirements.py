from sage.sap.requirements import (CheckEnv, FmAuthorized, FmExists, LoginOk, Reachable, SettingPresent, TableReadable)
from sage.sap.rfc import RfcError


def env(rfc, settings, **kw):
    return CheckEnv(rfc=rfc, system_id=1, rfc_user="RFCU", binding=kw.pop("binding", {}), settings=settings, **kw)


async def test_reachable_and_login(rfc, settings_store):
    assert (await Reachable().check(env(rfc, settings_store))).status == "pass"
    down = env(rfc, settings_store, ping_error=RfcError("CONNECT", "no route"))
    assert (await Reachable().check(down)).status == "fail"
    assert (await LoginOk().check(down)).status == "blocked"
    bad = env(rfc, settings_store, ping_error=RfcError("LOGIN", "denied"))
    assert (await Reachable().check(bad)).status == "pass"
    assert (await LoginOk().check(bad)).status == "fail"


async def test_fm_exists(rfc, settings_store, fake_rfc):
    fake_rfc.tables["TFDIR"] = [{"FUNCNAME": "ZFM_A"}]
    fake_rfc.lengths["TFDIR"] = {"FUNCNAME": 30}
    assert (await FmExists("ZFM_A").check(env(rfc, settings_store))).status == "pass"
    assert (await FmExists("ZFM_B").check(env(rfc, settings_store))).status == "fail"


async def test_fm_authorized_heuristic_and_unknown(rfc, settings_store, fake_rfc):
    vals = lambda **_: {"VALUES": [  # noqa: E731
        {"FIELD": "RFC_TYPE", "VON": "FUNC", "BIS": ""}, {"FIELD": "RFC_NAME", "VON": "ZFG_*", "BIS": ""},
        {"FIELD": "ACTVT", "VON": "16", "BIS": ""}]}
    fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = vals
    assert (await FmAuthorized("ZFM_X", group="ZFG_A").check(env(rfc, settings_store))).status == "pass"
    assert (await FmAuthorized("OTHER_FM").check(env(rfc, settings_store))).status == "fail"
    del fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"]
    assert (await FmAuthorized("ZFM_X").check(env(rfc, settings_store))).status == "warn"   # cannot verify


async def test_table_readable_and_setting(rfc, settings_store, fake_rfc):
    assert (await TableReadable("NOPE").check(env(rfc, settings_store))).status == "fail"
    fake_rfc.tables["T"], fake_rfc.lengths["T"] = [{"A": "1"}], {"A": 5}
    assert (await TableReadable("T").check(env(rfc, settings_store))).status == "pass"
    assert (await SettingPresent("default_variant").check(env(rfc, settings_store))).status == "fail"
    assert (await SettingPresent("default_variant", level="warn").check(env(rfc, settings_store))).status == "warn"
    assert (await SettingPresent("default_variant").check(env(rfc, settings_store, binding={"default_variant": "V1"}))).status == "pass"


def test_auth_rows():
    assert ("S_RFC", "RFC_NAME", "ZFM_X") in FmAuthorized("ZFM_X").auth_rows()
    assert ("S_TABU_NAM", "TABLE", "VARID") in TableReadable("VARID").auth_rows()
