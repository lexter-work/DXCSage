"""Setup guide for a workflow on a system. Generated from the declared requirements, never stored."""
from pathlib import Path

_RFC_DIR = Path(__file__).parent / "static" / "rfc"

_DEFAULT_GUIDE = {
    "reachable": "Make the application server reachable from the Sage host (network route, firewall, SAP router, sysnr).",
    "login": "Create a dialog or system RFC user in the client, with the password registered in Sage. Check for a locked or expired user.",
    "fm_exists": "Create the function module in SE37 (remote-enabled) in the function group and transport it to this system.",
    "fm_authorized": "Add S_RFC to the RFC user's role so the function (or its group) may be called remotely with ACTVT 16.",
    "table_readable": "Add S_TABU_NAM (or S_TABU_DIS for the table's authorization group) with ACTVT 03 for the table.",
    "setting": "Fill in this value on the workflow setup page.",
    "auth_declared": "These values are checked inside a standard SAP report, so no scan can find them. Ask the security team to add them to the RFC user's role.",
    "auth_coverage": "Compares every authorization value the workflow needs with the RFC user. Send the missing values to the security team in one request (see the table on this page).",
}


def load_source(name: str) -> str:
    return (_RFC_DIR / name).read_text(encoding="utf-8", errors="replace")


def build_guide(wf_cls, system: dict, rows: list[dict] | None, names: dict[str, str] | None = None, auth: dict | None = None) -> dict:
    names = {k: v for k, v in (names or {}).items() if k != v}
    ids = sorted(names, key=len, reverse=True)

    def sub(t):  # setup text and ABAP source are written with the IDs; show this system's names instead
        for oid in ids:
            t = t.replace(oid, names[oid])
        return t

    status = {(r["req_kind"], r["req_key"]): r for r in rows or []}
    steps, auth_table, seen = [], [], set()
    for r in wf_cls.requirements():
        res = status.get((r.kind, r.key))
        steps.append({
            "kind": r.kind, "key": r.key, "name": names.get(r.key, r.key),
            "title": sub(r.title()) + (f" (ID {r.key})" if r.key in names else ""),
            "text": sub((r.guide or _DEFAULT_GUIDE.get(r.kind, "")).replace("{sid}", system["sid"]).replace(
                "{client}", system["client"]).replace("{user}", system["rfc_user"])),
            "source": r.source, "source_text": sub(load_source(r.source)) if r.source else None,
            "status": res["status"] if res else None, "message": res["message"] if res else "",
        })
        for row in r.auth_rows(names):
            if row not in seen:
                seen.add(row)
                auth_table.append(list(row))
    return {"workflow": wf_cls.name, "description": wf_cls.description,
            "system": {k: system[k] for k in ("label", "sid", "client", "rfc_user")},
            "steps": steps, "auth_table": auth_table, "auth_coverage": auth or {"rows": [], "checked_at": None},
            "abap_objects": [{"object_id": oid, "kind": kind, "name": names.get(oid, oid)} for oid, kind in wf_cls.abap_objects()]}


def guide_markdown(g: dict) -> str:
    s = g["system"]
    out = [f"# Setup guide: {g['workflow']} on {s['label']} ({s['sid']}, client {s['client']})", "",
           g["description"], "", f"RFC user: `{s['rfc_user']}`", "", "## Steps", ""]
    for i, st in enumerate(g["steps"], 1):
        flag = f" [{st['status']}]" if st["status"] else ""
        out += [f"{i}. **{st['title']}**{flag}", f"   {st['text']}"]
        if st["message"]:
            out.append(f"   Last check: {st['message']}")
        if st["source_text"]:
            out += ["", "```abap", st["source_text"], "```"]
    out += ["", "## Authorizations for the RFC user's role", "", "| Object | Field | Value |", "|---|---|---|"]
    out += [f"| {o} | {f} | {v} |" for o, f, v in g["auth_table"]]
    return "\n".join(out) + "\n"
