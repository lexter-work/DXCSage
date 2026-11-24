import pytest
from sage.sap.rfc import RfcError, classify_abap_key, split_where

DD03L = [
    {"TABNAME": "ZWIDE", "FIELDNAME": "MANDT", "POSITION": "1", "KEYFLAG": "X"},
    {"TABNAME": "ZWIDE", "FIELDNAME": "ID", "POSITION": "2", "KEYFLAG": "X"},
    {"TABNAME": "ZWIDE", "FIELDNAME": "A", "POSITION": "3", "KEYFLAG": ""},
    {"TABNAME": "ZWIDE", "FIELDNAME": "B", "POSITION": "4", "KEYFLAG": ""},
]


def wide_fake(fake):
    fake.tables["DD03L"] = DD03L
    fake.lengths["DD03L"] = {"TABNAME": 30, "FIELDNAME": 30, "POSITION": 4, "KEYFLAG": 1}
    fake.lengths["ZWIDE"] = {"MANDT": 3, "ID": 10, "A": 300, "B": 300}
    fake.tables["ZWIDE"] = [{"MANDT": "100", "ID": str(i), "A": f"a{i}", "B": f"b{i}"} for i in range(3)]


def test_split_where_keeps_tokens_and_limit():
    w = " AND ".join(f"FIELD{i} = 'VALUE{i}'" for i in range(12))
    lines = [l["TEXT"] for l in split_where(w)]
    assert all(len(l) <= 72 for l in lines) and " ".join(x.strip() for x in lines) == w
    with pytest.raises(RfcError) as e:
        split_where("X" * 80)
    assert e.value.code == "WHERE_TOO_LONG"


def test_classify():
    assert classify_abap_key("TABLE_NOT_AVAILABLE") == "TABLE_NOT_AVAILABLE"
    assert classify_abap_key("FU_NOT_FOUND") == "FM_NOT_FOUND"
    assert classify_abap_key("NO_AUTHORIZATION") == "AUTH"
    assert classify_abap_key("OTHER") == "ABAP"


async def test_read_table_single_call(rfc, fake_rfc):
    fake_rfc.tables["T"] = [{"A": "1", "B": "x"}, {"A": "2", "B": "y"}]
    fake_rfc.lengths["T"] = {"A": 5, "B": 5}
    r = await rfc.read_table(1, "T", ["A", "B"], "B = 'y'")
    assert r.rows == [{"A": "2", "B": "y"}] and r.truncated is False


async def test_read_table_truncated(rfc, fake_rfc, settings_store):
    await settings_store.set("sap.rowcount_cap", 2, "t")
    fake_rfc.tables["T"] = [{"A": str(i)} for i in range(5)]
    fake_rfc.lengths["T"] = {"A": 5}
    r = await rfc.read_table(1, "T", ["A"])
    assert len(r.rows) == 2 and r.truncated is True


async def test_read_table_wide_fields_split_and_merged_by_key(rfc, fake_rfc):
    wide_fake(fake_rfc)
    r = await rfc.read_table(1, "ZWIDE", ["A", "B"])
    assert r.rows[1] == {"A": "a1", "B": "b1"}
    reads = [p for f, p in fake_rfc.calls if f == "RFC_READ_TABLE" and p["QUERY_TABLE"] == "ZWIDE" and p.get("NO_DATA") != "X"]
    assert len(reads) == 2                                   # A and B cannot share one 512-byte row


async def test_unstable_order_rejected(rfc, fake_rfc, settings_store):
    wide_fake(fake_rfc)
    await settings_store.set("sap.rowcount_cap", 2, "t")      # truncated window differs per batch
    fake_rfc.unstable = True
    with pytest.raises(RfcError) as e:
        await rfc.read_table(1, "ZWIDE", ["A", "B"])
    assert e.value.code == "UNSTABLE_ORDER"


async def test_probe_and_error_passthrough(rfc, fake_rfc):
    with pytest.raises(RfcError) as e:
        await rfc.probe_table(1, "NOPE")
    assert e.value.code == "TABLE_NOT_AVAILABLE"
    fake_rfc.tables["T"] = [{"A": "1"}]
    fake_rfc.lengths["T"] = {"A": 5}
    await rfc.probe_table(1, "T")


async def test_connection_cached_per_system_and_dropped(rfc, fake_rfc):
    await rfc.ping(1)
    await rfc.ping(2)
    assert set(rfc._clients) == {1, 2} and fake_rfc.count("RFC_PING") == 2
    rfc.drop(1)
    assert set(rfc._clients) == {2}
