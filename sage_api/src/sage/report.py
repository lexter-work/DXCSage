"""The final report of a workflow call as an Excel workbook, built from what was stored: the input and the output of the call.

Generic on purpose, so every workflow has a report without code of its own:
  Summary   who, where, when, the status, then the single values of the result
  Input     what the workflow was given
  other     one sheet per part of the result that holds rows, at any depth
A list of objects is a table. A part nested inside a row goes to its own sheet, named by the path ("components risk detail"),
and each of its rows says which parent row it belongs to: 'Parent row' is the number in the 'Row' column of the parent sheet,
'Parent' is the first value of that row. Nothing reaches SAP. A value that starts with = + - or @ is stored as text,
so a cell from SAP can never run as a formula."""
import io
import json
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MAX_CELL = 32000                    # an Excel cell holds 32767 characters
MAX_ROWS = 100_000
HEAD = PatternFill("solid", fgColor="D9D9DE")
BAD_SHEET = re.compile(r"[\[\]:*?/\\]")


def _label(key: str) -> str:
    return str(key).replace("_", " ").strip().capitalize()


def _is_container(v) -> bool:
    """Needs a sheet of its own: a list that holds objects or lists, or an object that holds one. A flat object or a list of values stays in its cell."""
    if isinstance(v, dict):
        return any(_is_container(x) for x in v.values())
    return isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v)


def _cell(v) -> str | int | float:
    """Numbers stay numbers, a list of values is joined, a flat object reads as 'key: value; key: value'."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        return "; ".join(str(_cell(x)) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_cell(x)}" for k, x in v.items())
    return str(v)


def _put(ws, row: int, col: int, value, bold=False):
    c = ws.cell(row=row, column=col)
    if isinstance(value, str):
        c.value = value[:MAX_CELL]
        c.data_type = "s"                       # never a formula, whatever the text starts with
        c.alignment = Alignment(wrap_text=True, vertical="top")
    else:
        c.value = value
        c.alignment = Alignment(vertical="top")
    if bold:
        c.font, c.fill = Font(bold=True), HEAD
    return c


def _widths(ws):
    for col in ws.columns:
        longest = max((len(str(c.value).split("\n")[0]) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(longest + 2, 10), 70)


class _Names:
    def __init__(self, taken: list[str]):
        self.used = {t.lower() for t in taken}

    def new(self, path: str) -> str:
        base = (BAD_SHEET.sub(" ", path.replace(".", " ")).strip() or "Result")[:31]      # Excel allows 31 characters
        name, n = base, 1
        while name.lower() in self.used:
            n += 1
            name = f"{base[:31 - len(str(n)) - 1]} {n}"
        self.used.add(name.lower())
        return name


def _pairs(ws, rows: list[tuple[str, object]]):
    for i, (k, v) in enumerate(rows, 1):
        _put(ws, i, 1, _label(k), bold=True)
        _put(ws, i, 2, _cell(v))


class _Parts:
    """The parts of a value that need a sheet, collected first and written once, so the rows of every parent row share one sheet."""

    def __init__(self):
        self.sheets: dict[str, dict] = {}

    def add(self, path: str, value, parent=None):
        """parent is None for a part of the result itself, else (row number on the parent sheet, first value of that row)."""
        if isinstance(value, dict) and parent is None:                      # one group of values: a Field / Value sheet
            self.sheets[path] = {"pairs": True, "rows": [(None, value)]}
            for k, v in value.items():
                if _is_container(v):
                    self.add(f"{path}.{k}", v)
            return
        if isinstance(value, dict) and all(_is_container(v) for v in value.values()):      # a group with no values of its own: only its parts get sheets
            for k, v in value.items():
                self.add(f"{path}.{k}", v, parent)
            return
        items = [value] if isinstance(value, dict) else [x if isinstance(x, dict) else {"value": x} for x in value[:MAX_ROWS]]
        sheet = self.sheets.setdefault(path, {"pairs": False, "rows": []})
        for it in items:
            sheet["rows"].append((parent, it))
            n = len(sheet["rows"])
            first = next((_cell(v) for v in it.values() if not _is_container(v) and v not in (None, "")), "")
            for k, v in it.items():
                if _is_container(v):
                    self.add(f"{path}.{k}", v, (n, first))


def _write(wb, names: _Names, path: str, sheet: dict):
    ws = wb.create_sheet(names.new(path))
    rows = sheet["rows"]
    if sheet["pairs"]:
        _pairs(ws, [(k, v) for k, v in rows[0][1].items() if not _is_container(v)])
        _widths(ws)
        return
    cols: list[str] = []
    for _, it in rows:
        cols += [k for k in it if k not in cols and not _is_container(it[k])]
    nested = any(_is_container(v) for _, it in rows for v in it.values())
    child = any(p is not None for p, _ in rows)
    heads = (["Parent row", "Parent"] if child else []) + (["Row"] if nested else []) + [_label(k) for k in cols]
    for j, h in enumerate(heads, 1):
        _put(ws, 1, j, h, bold=True)
    for i, (p, it) in enumerate(rows, 2):
        vals = ((list(p) if p else ["", ""]) if child else []) + ([i - 1] if nested else []) + [_cell(it.get(k)) for k in cols]
        for j, v in enumerate(vals, 1):
            _put(ws, i, j, v)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    _widths(ws)


def build_report(meta: dict, call_input: dict, output: str | None) -> bytes:
    """meta: workflow, system, requested_by, started_at, ended_at, status, call_id, run_id. output: the stored JSON text, or an error text."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = [("Report", f"{meta['workflow']} (call {meta['call_id']}, run {meta['run_id']})"), ("Target system", meta.get("system") or "none"),
            ("Requested by", meta.get("requested_by") or ""), ("Started", meta.get("started_at") or ""), ("Ended", meta.get("ended_at") or ""),
            ("Status", "Completed" if meta["status"] == "ok" else "Failed" if meta["status"] == "error" else meta["status"])]
    try:
        data = json.loads(output) if output else None
    except ValueError:
        data = None
    names = _Names(["Summary", "Input"])
    body = wb.create_sheet("Input")
    inp = call_input or {}
    _pairs(body, [(k, v) for k, v in inp.items() if not _is_container(v)] or [("input", "none")])
    _widths(body)
    parts = _Parts()
    for k, v in inp.items():
        if _is_container(v):
            parts.add(f"input.{k}", v)
    singles: list = []
    if isinstance(data, (dict, list)):
        root = data if isinstance(data, dict) else {"result": data}
        singles = [(k, v) for k, v in root.items() if not _is_container(v)]
        for k, v in root.items():
            if _is_container(v):
                parts.add(str(k), v)
    elif output:
        singles.append(("Error" if meta["status"] == "error" else "Result", output))
    for path, sheet in parts.sheets.items():
        _write(wb, names, path, sheet)
    _pairs(ws, head + [("", "")] + singles)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 90
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
