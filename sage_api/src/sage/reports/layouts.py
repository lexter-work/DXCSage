"""One report layout per workflow. Each reads the stored result (a dict, so a result stored by an older version still works)
and says what goes on the Summary sheet and which sheets follow. Keep them plain: a reader should find the answer on the
Summary and the evidence in the sheets."""
from collections import Counter

from sage.reports.kit import Report, severity_key, yes_no

CATEGORY = {"uninstallable": "Uninstallable", "not_uninstallable": "Not uninstallable", "protected": "Protected", "not_installed": "Not installed"}
AI_CATEGORY = {"sap_core": "SAP core or technical base", "industry_solution": "SAP industry or line-of-business solution", "sap_optional": "Optional SAP add-on",
               "partner_or_customer": "Partner or customer add-on", "unknown": "Could not be told"}
ACTION = {"add": "Add value", "remove": "Remove value", "modify": "Modify value", "remove_tcode": "Remove transaction code", "assign": "Assign", "unassign": "Unassign"}


def _g(d, key, default=None):
    v = d.get(key)
    return default if v is None else v


def _join(items) -> str:
    return ", ".join(str(x) for x in items or [])


# ---- pieces shared by the review and change workflows ----
def _findings(r: Report, rv: dict):
    errors, warnings = _g(rv, "errors", []), _g(rv, "warnings", [])
    r.bullets("Errors", errors, "bad")
    r.bullets("Warnings", warnings, "warn")
    if rv.get("next_step"):
        r.bullets("The AI still has to", [rv["next_step"]], "warn")
    r.table("Findings", ["Type", "Detail"], [["Error", e] for e in errors] + [["Warning", w] for w in warnings], [12, 130], tone=("Type",), empty="No errors or warnings.")


def _policies(r: Report, rv: dict):
    pol = _g(rv, "policies", [])
    if not pol:
        return
    pending = sum(p["state"] == "pending" for p in pol)
    withf = sum(bool(p.get("findings")) for p in pol)
    r.fact("Written policies", f"{len(pol)} checked, {pending} not reviewed yet, {withf} with findings", "bad" if pending or withf else "good")
    rows = [[p["name"], p["state"].upper(), "User roles" if p.get("kind") == "user_role" else "Role authorizations", len(p.get("findings") or []),
             "\n".join((f"{f['role']}: " if f.get("role") else "") + f["description"] for f in p.get("findings") or [])] for p in pol]
    r.table("Policies", ["Policy", "State", "Request type", "Findings", "Detail"], rows, [30, 12, 22, 10, 100], tone=("State",))


def _conflicts(r: Report, name: str, key: str, items: list[dict]):
    """items: dicts with the subject (a user or a role) under `key`, conflicts_after and introduced."""
    rows = []
    for it in items:
        new = set(it.get("introduced") or [])
        for c in sorted(it.get("conflicts_after") or [], key=lambda c: (severity_key(c["severity"]), c["rule_id"])):
            rows.append([it[key], c["rule_id"], c["severity"], "NEW" if c["rule_id"] in new else "Existing", _join(c.get("roles")), c.get("conflicting_objects", ""),
                         c.get("rule_description", ""), c.get("recommendation", "")])
    r.table(name, [_label_of(key), "Rule", "Severity", "Status", "Roles", "Conflicting objects", "Description", "Recommendation"], rows,
            [16, 12, 11, 11, 30, 40, 60, 60], tone=("Severity", "Status"), empty="No segregation-of-duties conflicts after the change.")
    return rows


def _label_of(key: str) -> str:
    return {"username": "User", "role": "Role"}.get(key, key.capitalize())


def _verdict(r: Report, rv: dict, executed: bool | None, message: str):
    ok = bool(rv.get("ready"))
    if executed is None:
        r.fact("Verdict", "Ready to apply" if ok else "Not ready", "good" if ok else "bad")
    else:
        r.fact("Verdict", "Applied to SAP" if executed else "Nothing was changed", "good" if executed else "bad")
        r.fact("Message", message)


# ---- user roles ----
def user_role(r: Report, change: bool):
    o = r.out
    rv = o.get("review") or {} if change else o
    r.use(*(("executed", "review", "results", "message") if change else ("ready", "errors", "warnings", "changes", "users", "unverified_roles", "policies", "next_step")))
    results = _g(o, "results", []) if change else []
    _verdict(r, rv, o.get("executed") if change else None, _g(o, "message", ""))
    users, changes = _g(rv, "users", []), _g(rv, "changes", [])
    new = sorted({i for u in users for i in u.get("introduced") or []})
    r.fact("Users affected", len(users))
    r.fact("Role changes requested", len(changes))
    r.fact("New conflicts introduced", len(new), "bad" if new else "good")
    if change and o.get("executed"):
        bad = [x for x in results if not x.get("success")]
        r.fact("Verified after the change", f"{len(results) - len(bad)} of {len(results)}", "bad" if bad else "good")
    if rv.get("unverified_roles"):
        r.fact("Roles not fully read", _join(rv["unverified_roles"]), "warn")
    _findings(r, rv)
    _policies(r, rv)
    res_by_row = {}
    if change and len(results) == len(changes):
        for u in sorted({c["username"] for c in changes}):
            for c in (x for x in changes if x["username"] == u):
                res_by_row[(u, c["role"], c["action"])] = results[len(res_by_row)]
    head = ["User", "Role", "Action"] + (["Result", "Note"] if res_by_row else [])
    rows = [[c["username"], c["role"], ACTION.get(c["action"], c["action"])] + (
        [("OK" if res_by_row[(c["username"], c["role"], c["action"])]["success"] else "FAILED"), res_by_row[(c["username"], c["role"], c["action"])]["note"]] if res_by_row else [])
        for c in changes]
    r.table("Changes", head, rows, [16, 30, 12, 10, 60], tone=("Result",), empty="No changes in the request.")
    r.table("Users", ["User", "Roles now", "Roles after", "Roles added", "Roles removed", "Conflicts now", "Conflicts after", "New conflicts"],
            [[u["username"], _join(u.get("roles_now")), _join(u.get("roles_after")), _join(sorted(set(u.get("roles_after") or []) - set(u.get("roles_now") or []))),
              _join(sorted(set(u.get("roles_now") or []) - set(u.get("roles_after") or []))), len(u.get("conflicts_now") or []), len(u.get("conflicts_after") or []),
              _join(u.get("introduced"))] for u in users], [16, 40, 40, 30, 30, 12, 12, 24], empty="No users.")
    _conflicts(r, "Conflicts after", "username", users)
    if change:
        r.table("Execution", ["Role", "Action", "Result", "Note"],
                [[x["role"], ACTION.get(x["action"], x["action"]), "OK" if x["success"] else "FAILED", x["note"]] for x in results], [30, 12, 10, 90], tone=("Result",),
                empty="Nothing was sent to SAP.")


# ---- role authorizations ----
def role_auth(r: Report, change: bool):
    o = r.out
    rv = o.get("review") or {} if change else o
    r.use(*(("executed", "review", "changes_applied", "tcode_results", "derived_regenerated", "message") if change
            else ("ready", "errors", "warnings", "violations", "changes", "roles", "unverified_roles", "policies", "next_step")))
    applied, tcodes, derived = (_g(o, "changes_applied", []), _g(o, "tcode_results", []), _g(o, "derived_regenerated", [])) if change else ([], [], [])
    _verdict(r, rv, o.get("executed") if change else None, _g(o, "message", ""))
    roles, changes, viol = _g(rv, "roles", []), _g(rv, "changes", []), _g(rv, "violations", [])
    new = sorted({i for x in roles for i in x.get("introduced") or []})
    r.fact("Roles affected", len(roles))
    r.fact("Changes requested", len(changes))
    r.fact("Policy violations", len(viol), "bad" if viol else "good")
    r.fact("New conflicts introduced", len(new), "bad" if new else "good")
    if rv.get("unverified_roles"):
        r.fact("Roles not fully read", _join(rv["unverified_roles"]), "warn")
    if change and o.get("executed"):
        failed = [x for x in (*applied, *tcodes, *derived) if not x.get("success")]
        r.fact("Steps that failed", len(failed), "bad" if failed else "good")
    _findings(r, rv)
    _policies(r, rv)
    head = ["Role", "Action", "Object", "Field", "Current value", "Requested value"] + (["Result", "Note"] if change and o.get("executed") else [])
    rows = []
    for c in changes:
        row = [c["role"], ACTION.get(c["action"], c["action"]), c.get("object", ""), ("Organization level " if c.get("field", "").startswith("$") else "") + c.get("field", ""),
               c.get("current_value", "") if c["action"] == "modify" else (c["value"] if c["action"] in ("remove", "remove_tcode") else ""),
               c["value"] if c["action"] in ("add", "modify") else ""]
        if change and o.get("executed"):
            if c["action"] == "remove_tcode":
                t = next((x for x in tcodes if x["role"] == c["role"] and x["tcode"] == c["value"]), None)
            else:
                mine = [x for x in applied if x["role"] == c["role"]]
                t = {"success": all(x["success"] for x in mine), "message": " ".join(x["message"] for x in mine)} if mine else None
            row += [("OK" if t["success"] else "FAILED") if t else "NOT RUN", t["message"] if t else "An earlier role failed, so this one was not touched."]
        rows.append(row)
    r.table("Changes", head, rows, [24, 22, 18, 22, 18, 18, 10, 70], tone=("Result",), empty="No changes in the request.")
    r.table("Policy violations", ["Role", "Object", "Policy", "Description"], [[v["role"], v["object"], v["policy"], v["description"]] for v in viol], [24, 18, 34, 100],
            empty="No policy violations.")
    r.table("Roles", ["Role", "Derived roles", "Conflicts now", "Conflicts after", "New conflicts"],
            [[x["role"], _join(x.get("derived_children")), len(x.get("conflicts_now") or []), len(x.get("conflicts_after") or []), _join(x.get("introduced"))] for x in roles],
            [30, 40, 14, 14, 24], empty="No roles.")
    _conflicts(r, "Conflicts after", "role", roles)
    if change:
        rows = ([["Authorization values", x["role"], "", "OK" if x["success"] else "FAILED", "", x["message"]] for x in applied]
                + [["Transaction code removal", x["role"], x["tcode"], "OK" if x["success"] else "FAILED", x.get("removed_values", 0), x["message"]] for x in tcodes]
                + [["Derived role regeneration", x["role"], "", "OK" if x["success"] else "FAILED", "", x["message"]] for x in derived])
        r.table("Execution", ["Step", "Role", "Transaction", "Result", "Values removed", "Message"], rows, [28, 28, 14, 10, 14, 100], tone=("Result",),
                empty="Nothing was sent to SAP.")


# ---- the other workflows ----
def sod_check(r: Report):
    o = r.out
    r.use(*o.keys())
    r.fact("User", o.get("username"))
    r.fact("User exists in SAP", yes_no(o.get("user_exists")), "good" if o.get("user_exists") else "bad")
    r.fact("Roles checked", len(_g(o, "roles_checked", [])))
    r.fact("Conflicts found", _g(o, "total_conflicts", 0), "bad" if o.get("total_conflicts") else "good")
    r.fact("Critical conflict", yes_no(o.get("has_critical")), "bad" if o.get("has_critical") else "good")
    r.fact("Roles not fully read", _join(o.get("unverified_roles")) or "none", "warn" if o.get("unverified_roles") else "good")
    r.bullets("Message", [o["message"]] if o.get("message") else [])
    sev = Counter(c["severity"] for c in _g(o, "conflicts", []))
    for s in sorted(sev, key=severity_key):
        r.fact(f"{s.capitalize()} conflicts", sev[s], "bad" if s in ("CRITICAL", "HIGH") else "warn")
    r.table("Conflicts", ["Rule", "Severity", "Roles", "Conflicting objects", "Description", "Recommendation"],
            [[c["rule_id"], c["severity"], _join(c.get("roles")), c.get("conflicting_objects", ""), c.get("rule_description", ""), c.get("recommendation", "")]
             for c in sorted(_g(o, "conflicts", []), key=lambda c: (severity_key(c["severity"]), c["rule_id"]))],
            [12, 11, 34, 44, 60, 60], tone=("Severity",), empty="No segregation-of-duties conflicts.")
    unread = set(o.get("unverified_roles") or [])
    r.table("Roles checked", ["Role", "Fully read"], [[x, "No" if x in unread else "Yes"] for x in _g(o, "roles_checked", [])], [34, 12], tone=("Fully read",))


def sum_status(r: Report):
    o = r.out
    r.use(*o.keys())
    r.fact("State", o.get("state"))
    r.fact("Phase", o.get("phase") or "")
    if o.get("phase_detail"):
        r.fact("Phase detail", o["phase_detail"])
    if o.get("progress_pct") is not None:
        r.fact("Progress", f"{o['progress_pct']:.0f}%")
    r.fact("Expected end", o.get("eta") or "unknown")
    r.fact("Time remaining", o.get("time_remaining") or "unknown")
    r.fact("Read from", o.get("source") or "")
    r.bullets("Last message", [o["message"]] if o.get("message") else [])
    r.bullets("What to do", [o["required_action"]] if o.get("required_action") else [], "warn" if o.get("state") in ("ERROR", "POSSIBLE_HANG", "PROCESS_DEAD") else None)
    d = o.get("diagnosis")
    if d:
        r.fact("Diagnosis", f"{d.get('error_code')} - {d.get('root_cause')}", "bad")
        r.table("Diagnosis", ["Field", "Value"], [["Error code", d.get("error_code")], ["Category", d.get("category")], ["Severity", d.get("severity")], ["Root cause", d.get("root_cause")],
                                                   ["Recommended fix", d.get("recommended_fix")], ["SAP Note", d.get("sap_note")], ["Recovers by itself", yes_no(d.get("auto_recoverable"))],
                                                   ["Matched text", d.get("matched_text")]], [22, 120])
    if o.get("raw_error_context"):
        r.lines("Error context", o["raw_error_context"], "Log excerpt around the error")


def readiness(r: Report):
    o = r.out
    r.use(*o.keys())
    notes = _g(o, "notes", [])
    r.fact("Data collection job", f"{o.get('job_name')} ({o.get('job_count')})")
    r.fact("Job result", o.get("final_status"), None)
    r.fact("Result file", o.get("filename") or o.get("file_path") or "")
    r.fact("File size", f"{(o.get('size_bytes') or 0) / 1024:.0f} KB")
    needed = [n for n in notes if not n.get("conditional")]
    open_ = [n for n in needed if not n.get("present") or n.get("implemented") is False]
    r.fact("Required SAP Notes", f"{len(needed) - len(open_)} of {len(needed)} in place", "bad" if open_ else "good")
    r.bullets("Notes to deal with", [f"{n['number']}: " + ("not in the system" if not n.get("present") else "not implemented") for n in open_], "bad")

    def state(n):
        if not n.get("present"):
            return "REVIEW" if n.get("conditional") else "MISSING"
        return {True: "IMPLEMENTED", False: "NOT IMPLEMENTED", None: "UNKNOWN"}[n.get("implemented")]
    r.table("SAP Notes", ["Note", "Needed", "Downloaded to the system", "Implemented", "Status"],
            [[n["number"], "Only in some cases" if n.get("conditional") else "Required", yes_no(n.get("present")),
              {True: "Yes", False: "No", None: "Not known"}[n.get("implemented")], state(n)] for n in notes], [14, 20, 24, 14, 20], tone=("Status",))


def obsolete(r: Report):
    o = r.out
    r.use(*o.keys())
    sample = _g(o, "sample", [])
    r.fact("Scan job", f"{o.get('job_name')} ({o.get('job_count')})")
    r.fact("Obsolete entries found", o.get("total", 0), "warn" if o.get("total") else "good")
    r.fact("Roles affected", o.get("roles", 0))
    r.fact("Full list on the server", o.get("file_path") or "")
    r.bullets("Note", [o["note"]] if o.get("note") else [])
    if (o.get("total") or 0) > len(sample):
        r.bullets("Not complete here", [f"These sheets hold the first {len(sample)} of {o['total']} entries. The full list is the file named above."], "warn")
    by = Counter(e["role"] for e in sample)
    r.table("By role", ["Role", "Obsolete transaction codes"], [[k, by[k]] for k in sorted(by, key=lambda k: (-by[k], k))], [34, 28], empty="No obsolete transaction codes.")
    r.table("Removal request", ["Role", "Tcode"], [[e["role"], e["tcode"]] for e in sample], [34, 20], empty="No obsolete transaction codes.")


def auth_requirements(r: Report):
    o = r.out
    r.use(*o.keys())
    wfs = _g(o, "workflows", [])
    merged: dict[tuple, list[str]] = {}
    for w in wfs:
        for v in w.get("values") or []:
            merged.setdefault((v["object"], v["field"], v["value"]), []).append(w["workflow"])
    r.fact("System", o.get("system"))
    r.fact("Workflows covered", len(wfs))
    r.fact("Different values to request", len(merged))
    unresolved = [[w["workflow"], u] for w in wfs for u in w.get("unresolved") or []]
    errors = [[w["workflow"], e] for w in wfs for e in w.get("errors") or []]
    r.fact("Values the scan could not resolve", len(unresolved), "warn" if unresolved else "good")
    r.fact("Workflows with errors", len({w for w, _ in errors}), "bad" if errors else "good")
    r.table("To request", ["Object", "Field", "Value", "Needed by"], [[*k, _join(sorted(set(v)))] for k, v in sorted(merged.items())], [20, 18, 30, 70],
            empty="No authorizations found.")
    r.table("By workflow", ["Workflow", "Object", "Field", "Value", "Source"],
            [[w["workflow"], v["object"], v["field"], v["value"], v["source"]] for w in wfs for v in w.get("values") or []], [30, 20, 18, 30, 40])
    if unresolved:
        r.table("Not resolved", ["Workflow", "Item"], unresolved, [30, 100])
    if errors:
        r.table("Errors", ["Workflow", "Error"], errors, [30, 120], empty="")


def addon(r: Report):
    o = r.out
    r.use(*o.keys())
    comps = _g(o, "components", [])
    count = Counter(c["category"] for c in comps)
    r.fact("System", o.get("system"))
    for k in ("uninstallable", "not_uninstallable", "protected", "not_installed"):
        if count[k]:
            r.fact(CATEGORY[k], count[k], "good" if k == "uninstallable" else "bad" if k == "not_uninstallable" else None)
    high = [c["component"] for c in comps if c.get("risk") == "HIGH"]
    r.fact("High risk", _join(high) or "none", "bad" if high else "good")
    r.bullets("Next step", [o["next_step"]] if o.get("next_step") else [], "warn")
    r.bullets("Note", [o["note"]] if o.get("note") else [])
    r.table("Components", ["Component", "Result", "Release", "Current patch", "Deinstall class", "Risk", "Repository objects", "Custom objects", "Required by", "Requires",
                           "Dependencies read", "AI category (judgment)", "Confidence", "AI reason", "Why"],
            [[c["component"], CATEGORY.get(c["category"], c["category"]).upper(), c.get("release", ""), c.get("current_patch", ""), c.get("deinstall_plugin", ""), c.get("risk", ""),
              c.get("objects_total", 0), c.get("custom_objects", 0), _join(c.get("required_by")), _join(c.get("requires")), yes_no(c.get("dependencies_checked")),
              AI_CATEGORY.get((c.get("classification") or {}).get("category"), ""), (c.get("classification") or {}).get("confidence", ""), (c.get("classification") or {}).get("reason", ""),
              c.get("reason", "")] for c in comps],
            [16, 20, 10, 14, 30, 9, 12, 10, 24, 24, 12, 30, 11, 50, 60], tone=("Result", "Risk"))
    r.table("Risk factors", ["Component", "Risk", "Factor"], [[c["component"], c.get("risk", ""), f] for c in comps for f in c.get("risk_factors") or []], [16, 9, 110],
            tone=("Risk",), empty="No risk factors.")
    r.table("Objects by type", ["Component", "Object type", "Count"], [[c["component"], t, n] for c in comps for t, n in sorted((c.get("objects_by_type") or {}).items())], [16, 14, 10],
            empty="No repository objects found.")
    r.table("Custom objects", ["Component", "Object type and name"], [[c["component"], x] for c in comps for x in c.get("custom_sample") or []], [16, 70],
            empty="No custom objects found in the packages.")
    for c in comps:
        if c.get("work_order"):
            r.lines(f"Work order {c['component']}", c["work_order"], f"Basis work order for {c['component']}")


def policy_record(r: Report):
    r.use("recorded", "message")
    r.fact("Policy", r.input.get("policy_name") or "")
    r.fact("Request type", r.input.get("kind") or "")
    r.fact("Findings given", len(r.input.get("findings") or []))
    r.fact("Recorded", yes_no(r.out.get("recorded")), "good" if r.out.get("recorded") else "bad")
    r.bullets("Message", [r.out["message"]] if r.out.get("message") else [])
    r.table("Findings", ["Role", "Finding"], [[f.get("role", ""), f.get("description", "")] for f in r.input.get("findings") or []], [24, 120], empty="No findings: the request meets the policy.")


LAYOUTS = {
    "sap_readiness_check": ("SAP Readiness Check", readiness),
    "sap_obsolete_tcodes": ("Obsolete transaction codes", obsolete),
    "sap_auth_requirements": ("Authorization requirements", auth_requirements),
    "sap_user_sod_check": ("Segregation of duties check of a user", sod_check),
    "sap_addon_uninstall_guide": ("Add-on uninstall guide", addon),
    "sap_user_role_review": ("User role change: review", lambda r: user_role(r, False)),
    "sap_user_role_change": ("User role change", lambda r: user_role(r, True)),
    "sap_role_auth_review": ("Role authorization change: review", lambda r: role_auth(r, False)),
    "sap_role_auth_change": ("Role authorization change", lambda r: role_auth(r, True)),
    "sap_sum_status": ("SUM status", sum_status),
    "sap_record_policy_review": ("Policy review record", policy_record),
}
