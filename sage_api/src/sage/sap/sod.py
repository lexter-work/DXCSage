"""Segregation-of-duties rules and the check of one person's roles against them. Pure functions, no SAP access.

A rule is {id, object_1, object_2[, object_3 ...], activity_N (optional, comma-separated ACTVT codes), description,
risk_level, recommended_action}. A side is an authorization object name or a transaction code. A rule fires when every
side is granted by at least one of the person's roles; the sides may come from different roles.
"""
import re

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SAFE = re.compile(r"^[A-Za-z0-9_/.$#@-]{1,40}$")      # values that go into a table WHERE clause


def severity_rank(s: str) -> int:
    try:
        return SEVERITIES.index(s.upper())
    except (ValueError, AttributeError):
        return len(SEVERITIES)


def sides(rule: dict) -> list[tuple[str, str | None]]:
    out, i = [], 1
    while f"object_{i}" in rule:
        out.append((str(rule[f"object_{i}"]).upper(), rule.get(f"activity_{i}") or None))
        i += 1
    return out


def normalize_rules(matrix: dict) -> list[dict]:
    """Validate the stored matrix. Raises ValueError with a message the admin can act on."""
    rules = matrix.get("conflicts") if isinstance(matrix, dict) else None
    if not rules:
        raise ValueError("The SoD matrix (setting sod.matrix) has no rules.")
    out = []
    for r in rules:
        rid = str(r.get("id", "?"))
        s = sides(r)
        if len(s) < 2:
            raise ValueError(f"SoD rule {rid} needs at least object_1 and object_2.")
        for value, act in s:
            if not SAFE.match(value):
                raise ValueError(f"SoD rule {rid}: '{value}' is not a valid object or transaction name.")
            if act and not re.fullmatch(r"[A-Za-z0-9*, ]{1,40}", act):
                raise ValueError(f"SoD rule {rid}: activity '{act}' is not a list of codes like 01,02.")
        risk = str(r.get("risk_level", "")).upper()
        out.append({**r, "id": rid, "risk_level": risk if risk in SEVERITIES else "MEDIUM"})
    return out


def side_grants(value: str, required: str | None, objects: set[str], tcodes: set[str], activities: dict[str, set[str]]) -> bool:
    """Does one role satisfy one side? Without activity data for the object, presence alone counts: flagging a role we cannot
    fully describe is safer than clearing it."""
    if value not in objects and value not in tcodes:
        return False
    if required is None:
        return True
    granted = activities.get(value)
    if not granted:
        return True
    return bool({a.strip() for a in required.split(",") if a.strip()} & granted)


def conflicts_for_roles(rules: list[dict], roles: list[str], data: dict[str, dict]) -> list[dict]:
    """data[role] = {"objects": set, "tcodes": set, "activities": {object: set(ACTVT)}}. Most severe first."""
    found = []
    for rule in rules:
        sd = sides(rule)
        per_side = [sorted(r for r in roles if side_grants(v, a, **data[r])) for v, a in sd]
        if all(per_side):
            via = [f"{v} (via {', '.join(g)})" for (v, _), g in zip(sd, per_side)]
            found.append({
                "rule_id": rule["id"], "severity": rule["risk_level"], "roles": sorted({r for g in per_side for r in g}),
                "conflicting_objects": " vs ".join(via), "rule_description": rule.get("description", ""),
                "recommendation": rule.get("recommended_action") or "Remove one of the conflicting roles from this user, or split the access across separate users.",
            })
    found.sort(key=lambda c: severity_rank(c["severity"]))
    return found
