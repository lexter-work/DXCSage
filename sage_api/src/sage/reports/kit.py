"""The parts every workflow report is built from, so each layout only says what goes where.

A layout is a function that gets a Report and calls fact() / bullets() for the Summary sheet and table() / lines() for the other sheets.
The Summary sheet is always first, then the sheets in the order they were made, then the sheets for values the layout did not use
(so a field added to a workflow later still shows up), then Input. Cells with text are never formulas."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from sage.report import _cell, _is_container, _label, _Names, _Parts, _pairs, _put, _widths, _write

RED, AMBER, GREEN = "B3261E", "8A5A00", "1E6B34"
TONES = {**dict.fromkeys(("CRITICAL", "ERROR", "FAILED", "FAIL", "HIGH", "POSSIBLE_HANG", "PROCESS_DEAD", "BLOCKED", "NOT READY", "MISSING", "NO", "NEW", "NOT UNINSTALLABLE"), RED),
         **dict.fromkeys(("MEDIUM", "WARNING", "PENDING", "REVIEW", "UNKNOWN", "WAITING_INPUT", "OFFLINE", "NOT IMPLEMENTED", "NOT RUN", "PROTECTED"), AMBER),
         **dict.fromkeys(("OK", "COMPLETED", "SUCCESS", "LOW", "DONE", "READY", "IMPLEMENTED", "REVIEWED", "YES", "RUNNING", "UNINSTALLABLE"), GREEN)}
SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
SHEET_HEAD = PatternFill("solid", fgColor="D9D9DE")
BAND = PatternFill("solid", fgColor="F2F2F4")


def tone_of(value, tone=None) -> str | None:
    """A colour for a status word; tone forces one of 'bad', 'warn', 'good'."""
    if tone:
        return {"bad": RED, "warn": AMBER, "good": GREEN}[tone]
    return TONES.get(str(value).strip().upper())


def severity_key(s) -> int:
    return SEVERITY.get(str(s).upper(), 9)


def yes_no(v) -> str:
    return "Yes" if v else "No"


class Report:
    def __init__(self, title: str, meta: dict, call_input: dict, out: dict):
        self.title, self.meta, self.input, self.out = title, meta, call_input or {}, out
        self.wb = Workbook()
        self.summary = self.wb.active
        self.summary.title = "Summary"
        self.names = _Names(["Summary", "Input", "Other values"])
        self._items: list[tuple] = []
        self._used: set[str] = set()

    # ---- what the layout says ----
    def use(self, *keys: str):
        """Mark top-level result fields as shown by the layout."""
        self._used.update(keys)

    def fact(self, label: str, value, tone: str | None = None):
        self._items.append(("fact", label, value, tone))

    def section(self, title: str):
        self._items.append(("section", title))

    def bullets(self, title: str, items: list[str], tone: str | None = None, limit: int = 12):
        """A short list on the Summary: the first `limit` items, then a count of the rest."""
        if not items:
            return
        self.section(title)
        for x in items[:limit]:
            self._items.append(("bullet", x, tone))
        if len(items) > limit:
            self._items.append(("bullet", f"... and {len(items) - limit} more: see the sheet for the full list.", None))

    def table(self, name: str, headers: list[str], rows: list[list], widths: list[int] | None = None, tone: tuple[str, ...] = (), empty: str = "Nothing to show."):
        """One sheet: a header row, then the rows. tone: names of the columns that hold a status word to colour."""
        ws = self.wb.create_sheet(self.names.new(name))
        for j, h in enumerate(headers, 1):
            _put(ws, 1, j, h, bold=True)
        marks = {headers.index(t) for t in tone if t in headers}
        for i, row in enumerate(rows, 2):
            for j, v in enumerate(row, 1):
                c = _put(ws, i, j, _cell(v))
                color = tone_of(v) if (j - 1) in marks else None
                if color:
                    c.font = Font(bold=True, color=color)
        if not rows:
            _put(ws, 2, 1, empty)
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
        _widths(ws)
        for j, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        return ws

    def lines(self, name: str, text: str, title: str = "Text"):
        """A long text, one line per row, in a fixed-width font: a work order or a log excerpt."""
        ws = self.wb.create_sheet(self.names.new(name))
        _put(ws, 1, 1, title, bold=True)
        for i, line in enumerate(str(text).splitlines() or [""], 2):
            c = _put(ws, i, 1, line)
            c.font = Font(name="Consolas", size=10)
            c.alignment = Alignment(wrap_text=False, vertical="top")
        ws.column_dimensions["A"].width = 110
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    # ---- the file ----
    def _write_summary(self):
        ws, m = self.summary, self.meta
        _put(ws, 1, 1, self.title).font = Font(bold=True, size=15)
        _put(ws, 2, 1, f"{m['workflow']} - call {m['call_id']} - run {m['run_id']}").font = Font(color="666666")
        status = "Completed" if m["status"] == "ok" else "Failed" if m["status"] == "error" else m["status"]
        rows: list[tuple] = [("section", "Request"), ("fact", "Target system", m.get("system") or "none", None), ("fact", "Requested by", m.get("requested_by") or "", None),
                             ("fact", "Started", m.get("started_at") or "", None), ("fact", "Ended", m.get("ended_at") or "", None),
                             ("fact", "Call status", status, "good" if m["status"] == "ok" else "bad"), ("section", "Result")] + self._items
        r = 4
        for it in rows:
            if it[0] == "section":
                r += 1
                c = _put(ws, r, 1, it[1])
                c.font, c.fill = Font(bold=True), SHEET_HEAD
                ws.cell(row=r, column=2).fill = SHEET_HEAD
            elif it[0] == "fact":
                _, label, value, tone = it
                _put(ws, r, 1, label).font = Font(color="444444")
                c = _put(ws, r, 2, _cell(value))
                color = tone_of(value, tone)
                if color:
                    c.font = Font(bold=True, color=color)
            else:
                _, text, tone = it
                _put(ws, r, 1, "")
                c = _put(ws, r, 2, text)
                color = tone_of("", tone) if tone else None
                if color:
                    c.font = Font(color=color)
            r += 1
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 100
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    def finish(self) -> bytes:
        rest = {k: v for k, v in self.out.items() if k not in self._used}
        singles = [(k, v) for k, v in rest.items() if not _is_container(v)]
        parts = _Parts()
        for k, v in rest.items():
            if _is_container(v):
                parts.add(str(k), v)
        if singles:
            self.section("Other values")
            for k, v in singles:
                self.fact(_label(k), v)
        for path, sheet in parts.sheets.items():
            _write(self.wb, self.names, path, sheet)
        self._write_summary()
        body = self.wb.create_sheet("Input")
        inp = self.input
        _pairs(body, [(k, v) for k, v in inp.items() if not _is_container(v)] or [("input", "none")])
        _widths(body)
        extra = _Parts()
        for k, v in inp.items():
            if _is_container(v):
                extra.add(f"input.{k}", v)
        for path, sheet in extra.sheets.items():
            _write(self.wb, self.names, path, sheet)
        out = io.BytesIO()
        self.wb.save(out)
        return out.getvalue()
