import re

from sage.sap.rfc import RfcError


class FakeRfcClient:
    """Stands in for pyrfc. Implements RFC_READ_TABLE over in-memory tables."""

    def __init__(self, tables=None, lengths=None, functions=None):
        self.tables = tables or {}        # table -> list[dict]
        self.lengths = lengths or {}      # table -> {field: length}
        self.functions = functions or {}  # fm -> callable(**params) -> dict
        self.calls = []                   # (fm, params)
        self.unstable = False             # reverse row order on every other read

    def call(self, fm, **p):
        self.calls.append((fm, p))
        if fm == "RFC_PING":
            return {}
        if fm == "RFC_READ_TABLE":
            return self._read(p)
        if fm in self.functions:
            return self.functions[fm](**p)
        raise RfcError("FM_NOT_FOUND", fm)

    def close(self):
        pass

    def count(self, fm):
        return sum(1 for f, _ in self.calls if f == fm)

    def _read(self, p):
        t = p["QUERY_TABLE"]
        if t not in self.tables:
            raise RfcError("TABLE_NOT_AVAILABLE", t)
        names = [f["FIELDNAME"] for f in p.get("FIELDS", [])] or list(self.lengths[t])
        meta = [{"FIELDNAME": n, "LENGTH": self.lengths[t][n]} for n in names]
        if p.get("NO_DATA") == "X":
            return {"FIELDS": meta, "DATA": []}
        where = "".join(o["TEXT"] for o in p.get("OPTIONS", []))
        rows = [r for r in self.tables[t] if self._match(r, where)]
        if self.unstable and self.count("RFC_READ_TABLE") % 2 == 0:
            rows = list(reversed(rows))
        skip, count = p.get("ROWSKIPS", 0), p.get("ROWCOUNT", 0)
        rows = rows[skip: skip + count if count else None]
        data = [{"WA": "|".join(str(r.get(n, "")).ljust(self.lengths[t][n]) for n in names)} for r in rows]
        return {"FIELDS": meta, "DATA": data}

    @staticmethod
    def _match(row, where):
        if not where.strip():
            return True

        # conditions "FIELD = 'value'" joined by AND / OR, with parentheses
        expr = re.sub(r"(\w+) (=|<>|LIKE) '([^']*)'", lambda m: f"ok({m[1]!r}, {m[2]!r}, {m[3]!r})", where)
        expr = re.sub(r"\bAND\b", "and", re.sub(r"\bOR\b", "or", expr))

        def ok(field, op, value):
            have, want = str(row.get(field, "")).strip(), value.strip()
            if op == "LIKE":
                return re.fullmatch(re.escape(want).replace("%", ".*"), have) is not None
            return (have == want) == (op == "=")
        return bool(eval(expr, {"__builtins__": {}}, {"ok": ok}))
