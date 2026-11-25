"""Excel change requests (templates and parser) for the user-role and role-authorization workflows.

Three layouts, found by the header row, so the same upload works whatever the sheet is called:
  user_roles     Username, Role, Action (assign or unassign)
  role_auth      Role, Object, Field, Current Value, Requested Value, Action (add, modify or remove; blank is worked out)
  tcode_removal  Role, Tcode  (the CSV of sap_obsolete_tcodes has these columns, extra ones are ignored)
Rows come back as plain dicts in the shape of the workflow inputs, with one error text per bad row. Nothing here reaches SAP."""
import io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

MAX_ROWS = 2000
KINDS = {
    "user_roles": {"title": "User role changes", "columns": [("Username", True, "SAP user ID"), ("Role", True, "Role name"), ("Action", True, "assign or unassign")],
                   "examples": [("JSMITH", "Z_AP_CLERK", "assign"), ("JSMITH", "Z_AP_APPROVER", "unassign")], "actions": "assign,unassign"},
    "role_auth": {"title": "Role authorization changes",
                  "columns": [("Role", True, "Role name. Not an SAP_* standard role."), ("Object", True, "Authorization object, for example F_BKPF_BUK. Leave empty for an organization level."),
                              ("Field", True, "Authorization field, for example ACTVT, or an organization level with a $, for example $BUKRS"), ("Current Value", False, "The value to replace or remove (modify, remove)"),
                              ("Requested Value", False, "The value to add, or the new value (add, modify)"), ("Action", False, "add, modify or remove. Blank: worked out from the values.")],
                  "examples": [("Z_FI_POSTER", "F_BKPF_BUK", "ACTVT", "03", "02", "modify"), ("Z_FI_POSTER", "F_BKPF_BUK", "BUKRS", "", "1000", "add"),
                               ("Z_FI_POSTER", "F_BKPF_BUK", "BUKRS", "2000", "", "remove"),
                               ("Z_FI_POSTER", "", "$BUKRS", "", "3000", "add")], "actions": "add,modify,remove"},
    "tcode_removal": {"title": "Remove transaction codes from roles", "columns": [("Role", True, "Role name"), ("Tcode", True, "Transaction code to remove from the role menu and from S_TCODE")],
                      "examples": [("Z_BASIS_ADMIN", "SU01")], "actions": ""},
}
USER_ACTIONS = {"assign": "assign", "add": "assign", "grant": "assign", "unassign": "unassign", "remove": "unassign", "revoke": "unassign", "delete": "unassign"}
AUTH_ACTIONS = {"add": "add", "modify": "modify", "change": "modify", "remove": "remove", "delete": "remove"}


def build_template(kind: str) -> bytes:
    """A workbook with the header row on the first sheet (fill it in), the rules on 'Instructions' and sample rows on 'Examples'.
    The samples are on their own sheet so that an upload of the untouched template changes nothing."""
    spec = KINDS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = "Request"
    head = PatternFill("solid", fgColor="D9D9DE")
    for i, (name, required, _) in enumerate(spec["columns"], 1):
        c = ws.cell(row=1, column=i, value=name)
        c.font, c.fill = Font(bold=True), head
        ws.column_dimensions[c.column_letter].width = 22
    ws.freeze_panes = "A2"
    if spec["actions"]:
        dv = DataValidation(type="list", formula1=f'"{spec["actions"]}"', allow_blank=kind == "role_auth")
        ws.add_data_validation(dv)
        dv.add(f"{ws.cell(row=2, column=len(spec['columns'])).column_letter}2:{ws.cell(row=MAX_ROWS, column=len(spec['columns'])).column_letter}{MAX_ROWS}")
    ex = wb.create_sheet("Examples")
    ex.append([c[0] for c in spec["columns"]])
    for r in spec["examples"]:
        ex.append(list(r))
    for cell in ex[1]:
        cell.font = Font(bold=True)
    ins = wb.create_sheet("Instructions")
    lines = [spec["title"], "", "Fill in the sheet 'Request' from row 2. Do not rename the first row. Empty rows are ignored; at most %d rows are read." % MAX_ROWS,
             "Upload the file in the chat and ask Sage to review it first. A request is only applied after the review passes and you confirm.", "", "Columns"]
    lines += [f"{n}{' (required)' if req else ''}: {why}" for n, req, why in spec["columns"]]
    if kind == "role_auth":
        lines += ["", "Values of ACTVT are two characters: 2 is read as 02.", "An organization level starts with $ in Field (for example $BUKRS) and has no Object. The role must already have that level: add the level itself in PFCG. Derived roles keep their own organization values.", "Adding a whole new authorization object to a role is not supported: use PFCG."]
    ins.column_dimensions["A"].width = 110
    for i, t in enumerate(lines, 1):
        ins.cell(row=i, column=1, value=t).alignment = Alignment(wrap_text=True)
    ins["A1"].font = Font(bold=True, size=13)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _col(headers: list[str], *words: str) -> int:
    for i, h in enumerate(headers):
        if any(w in h for w in words):
            return i
    return -1


def detect(headers: list[str]) -> str | None:
    h = [str(x or "").strip().lower() for x in headers]
    if any("tcode" in c for c in h) and any("role" in c for c in h):
        return "tcode_removal"
    if any("user" in c for c in h) and any("role" in c for c in h) and any("action" in c for c in h):
        return "user_roles"
    if min(_col(h, "role"), _col(h, "object"), _col(h, "field")) >= 0 and (_col(h, "current") >= 0 or _col(h, "requested", "new") >= 0):
        return "role_auth"
    return None


def parse(data: bytes) -> dict:
    """{kind, rows, errors}. kind is None when no sheet has a known header row."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - not a workbook, or damaged
        return {"kind": None, "rows": [], "errors": ["The file is not a readable .xlsx workbook."]}
    try:
        for ws in wb.worksheets:
            if ws.title.lower() in ("instructions", "examples"):
                continue
            it = ws.iter_rows(values_only=True)
            headers = next(it, None)
            kind = detect(list(headers or []))
            if kind:
                rows, errors = _PARSERS[kind]([str(x or "").strip().lower() for x in headers], list(it)[:MAX_ROWS])
                return {"kind": kind, "rows": rows, "errors": errors}
    finally:
        wb.close()
    return {"kind": None, "rows": [], "errors": ["No sheet has a header row Sage knows. Start from one of the templates (the first row must stay as it is)."]}


def _user_roles(h, data):
    iu, ir, ia = _col(h, "user"), _col(h, "role"), _col(h, "action")
    rows, errors, seen = [], [], {}
    for n, r in enumerate(data, 2):
        u, role, act = (_text(r[i]) if i < len(r) else "" for i in (iu, ir, ia))
        if not (u or role or act):
            continue
        if not (u and role and act):
            errors.append(f"Row {n}: Username, Role and Action are all required.")
        elif act.lower() not in USER_ACTIONS:
            errors.append(f"Row {n}: unknown Action '{act}' (use assign or unassign).")
        else:
            rows.append({"username": u.upper(), "role": role.upper(), "action": USER_ACTIONS[act.lower()]})
            seen[(u.upper(), role.upper())] = n
    return rows, errors


def _role_auth(h, data):
    ir, io_, ifld, ic, iq, ia = _col(h, "role"), _col(h, "object"), _col(h, "field"), _col(h, "current"), _col(h, "requested", "new"), _col(h, "action")
    rows, errors = [], []
    for n, r in enumerate(data, 2):
        get = lambda i: _text(r[i]) if 0 <= i < len(r) else ""  # noqa: E731
        role, obj, fld, cur, req, act = get(ir), get(io_), get(ifld), get(ic), get(iq), get(ia).lower()
        if not (role or obj or fld or cur or req or act):
            continue
        if not (role and fld and (obj or fld.startswith("$"))):
            errors.append(f"Row {n}: Role and Field are required, and Object unless the Field is an organization level ($...).")
            continue
        fld = fld.upper()
        if fld.startswith("$"):
            obj = ""
        if fld == "ACTVT":
            cur, req = (v.zfill(2) if v.isdigit() and len(v) == 1 else v for v in (cur, req))
        act = AUTH_ACTIONS.get(act, act) or ("modify" if cur and req else "add" if req else "remove" if cur else "")
        if act not in ("add", "modify", "remove"):
            errors.append(f"Row {n}: could not work out the Action. Use add, modify or remove.")
        elif act == "add" and not req:
            errors.append(f"Row {n}: add needs a Requested Value.")
        elif act == "modify" and not (cur and req):
            errors.append(f"Row {n}: modify needs both a Current Value and a Requested Value.")
        elif act == "remove" and not (cur or req):
            errors.append(f"Row {n}: remove needs a value.")
        else:
            rows.append({"role": role.upper(), "action": act, "object": obj.upper(), "field": fld,
                         "value": req if act in ("add", "modify") else (cur or req), "current_value": cur if act == "modify" else ""})
    return rows, errors


def _tcodes(h, data):
    ir, it = _col(h, "role"), _col(h, "tcode")
    rows, errors = [], []
    for n, r in enumerate(data, 2):
        role, tcode = (_text(r[i]) if i < len(r) else "" for i in (ir, it))
        if not (role or tcode):
            continue
        if not (role and tcode):
            errors.append(f"Row {n}: Role and Tcode are both required.")
        else:
            rows.append({"role": role.upper(), "action": "remove_tcode", "object": "", "field": "", "value": tcode.upper(), "current_value": ""})
    return rows, errors


_PARSERS = {"user_roles": _user_roles, "role_auth": _role_auth, "tcode_removal": _tcodes}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")
