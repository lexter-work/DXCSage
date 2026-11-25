"""SAP access: PyRFC only. Reads use RFC_READ_TABLE; everything else is a named function module.

Not verified against a real SAP system from this repo: pyrfc_connector and the error mapping.
"""
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel

MAX_ROW = 512


class RfcError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class RfcParams:
    ashost: str
    sysnr: str
    client: str
    user: str
    passwd: str


class RfcClient(Protocol):
    def call(self, fm: str, **params) -> dict: ...
    def close(self) -> None: ...


class TableResult(BaseModel):
    rows: list[dict[str, str]]
    truncated: bool


def classify_abap_key(key: str) -> str:
    k = key.upper()
    if k in ("TABLE_NOT_AVAILABLE", "TABLE_WITHOUT_DATA"):
        return "TABLE_NOT_AVAILABLE"
    if k in ("FU_NOT_FOUND", "FUNCTION_NOT_FOUND"):
        return "FM_NOT_FOUND"
    if "AUTH" in k:
        return "AUTH"
    return "ABAP"


def split_where(where: str, width: int = 72) -> list[dict]:
    """OPTIONS lines are 72 chars; split on spaces and keep a trailing space as the joiner."""
    lines, cur = [], ""
    limit = width - 1                      # room for the trailing joiner space
    for tok in where.split():
        if len(tok) > limit:
            raise RfcError("WHERE_TOO_LONG", tok)
        if cur and len(cur) + 1 + len(tok) > limit:
            lines.append(cur + " ")
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    if cur:
        lines.append(cur)
    return [{"TEXT": line} for line in lines]


class _PyrfcClient:
    def __init__(self, conn, pyrfc):
        self._conn, self._p = conn, pyrfc

    def call(self, fm, **params):
        p = self._p
        try:
            return self._conn.call(fm, **params)
        except (p.ABAPApplicationError, p.ABAPRuntimeError) as e:
            raise RfcError(classify_abap_key(getattr(e, "key", "")), getattr(e, "message", str(e))) from e
        except p.CommunicationError as e:
            raise RfcError("CONNECT", str(e)) from e

    def close(self):
        self._conn.close()


def pyrfc_connector(p: RfcParams) -> RfcClient:
    try:
        import pyrfc
    except ImportError as e:
        raise RfcError("CONNECT", "pyrfc / SAP NW RFC SDK is not installed in this image") from e
    try:
        conn = pyrfc.Connection(ashost=p.ashost, sysnr=p.sysnr, client=p.client, user=p.user, passwd=p.passwd)
    except pyrfc.LogonError as e:
        raise RfcError("LOGIN", str(e)) from e
    except (pyrfc.CommunicationError, pyrfc.RFCError) as e:
        raise RfcError("CONNECT", str(e)) from e
    return _PyrfcClient(conn, pyrfc)


class SapRfc:
    def __init__(self, load_params: Callable[[int], Awaitable[RfcParams]],
                 connector: Callable[[RfcParams], RfcClient], settings,
                 load_names: Callable[[int], Awaitable[dict[str, str]]] | None = None):
        self._load, self._connector, self._settings, self._names = load_params, connector, settings, load_names
        self._clients: dict[int, RfcClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def drop(self, system_id: int) -> None:
        c = self._clients.pop(system_id, None)
        if c:
            try:
                c.close()
            except Exception:
                pass

    async def call(self, system_id: int, fm: str, **params) -> dict:
        # fm is an abap_object_id; a system with its own naming convention maps it to its own name.
        if self._names:
            fm = (await self._names(system_id)).get(fm, fm)
        async with self._locks.setdefault(system_id, asyncio.Lock()):
            for attempt in (0, 1):
                client = self._clients.get(system_id)
                if client is None:
                    client = await asyncio.to_thread(self._connector, await self._load(system_id))
                    self._clients[system_id] = client
                try:
                    return await asyncio.to_thread(client.call, fm, **params)
                except RfcError as e:
                    if e.code == "CONNECT" and attempt == 0:
                        self.drop(system_id)
                        continue
                    raise
        raise RfcError("CONNECT", "unreachable")

    async def ping(self, system_id: int) -> None:
        await self.call(system_id, "RFC_PING")

    async def test(self, params: RfcParams) -> None:
        """Connect and ping without touching the cache (used when registering a system)."""
        client = await asyncio.to_thread(self._connector, params)
        try:
            await asyncio.to_thread(client.call, "RFC_PING")
        finally:
            await asyncio.to_thread(client.close)

    async def probe_table(self, system_id: int, table: str) -> None:
        """Read one value of one column: proves the table exists and the account may read it."""
        meta = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, NO_DATA="X")
        first = meta["FIELDS"][0]["FIELDNAME"]
        await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, ROWCOUNT=1, DELIMITER="|",
                        FIELDS=[{"FIELDNAME": first}])

    async def _lengths(self, system_id, table, names) -> dict[str, int]:
        res = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, NO_DATA="X",
                              FIELDS=[{"FIELDNAME": n} for n in names])
        return {f["FIELDNAME"]: int(f["LENGTH"]) for f in res["FIELDS"]}

    async def _keys(self, system_id, table) -> list[str]:
        res = await self.call(
            system_id, "RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
            FIELDS=[{"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "POSITION"}],
            OPTIONS=split_where(f"TABNAME = '{table}' AND KEYFLAG = 'X'"))
        parsed = [[x.strip() for x in w["WA"].split("|")] for w in res["DATA"]]
        rows = sorted((int(v[1] or 0), v[0]) for v in parsed)
        keys = [name for _, name in rows if name != "MANDT" and not name.startswith(".")]
        if not keys:
            raise RfcError("NO_ORDER", f"{table} has no key fields; cannot split a wide read")
        return keys

    async def read_table(self, system_id: int, table: str, fields: list[str],
                         where: str = "", rows: int | None = None) -> TableResult:
        cap = int(await self._settings.get("sap.rowcount_cap"))
        limit = min(rows or cap, cap)
        opts = split_where(where)
        lengths = await self._lengths(system_id, table, fields)
        if sum(lengths.values()) + len(fields) <= MAX_ROW:
            batches, keys = [list(fields)], []
        else:
            keys = await self._keys(system_id, table)
            need = [k for k in keys if k not in lengths]
            if need:
                lengths.update(await self._lengths(system_id, table, need))
            keyw = sum(lengths[k] + 1 for k in keys)
            batches, cur, width = [], list(keys), keyw
            for f in (f for f in fields if f not in keys):
                if keyw + lengths[f] + 1 > MAX_ROW:
                    raise RfcError("TOO_WIDE", f"{table}.{f} plus the key does not fit in {MAX_ROW} bytes")
                if width + lengths[f] + 1 > MAX_ROW:
                    batches.append(cur)
                    cur, width = list(keys), keyw
                cur.append(f)
                width += lengths[f] + 1
            batches.append(cur)
        parsed = []
        for names in batches:
            res = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                  ROWCOUNT=limit + 1, FIELDS=[{"FIELDNAME": n} for n in names], OPTIONS=opts)
            parsed.append([dict(zip(names, (x.strip() for x in w["WA"].split("|")))) for w in res["DATA"]])
        truncated = len(parsed[0]) > limit
        parsed = [p[:limit] for p in parsed]
        if len(parsed) == 1:
            merged = parsed[0]
        else:
            kf = lambda r: tuple(r[k] for k in keys)  # noqa: E731
            base = {kf(r): dict(r) for r in parsed[0]}
            for other in parsed[1:]:
                if {kf(r) for r in other} != set(base):
                    raise RfcError("UNSTABLE_ORDER", f"{table}: batches returned different rows; narrow the fields")
                for r in other:
                    base[kf(r)].update(r)
            merged = list(base.values())
        return TableResult(rows=[{f: r[f] for f in fields} for r in merged], truncated=truncated)
