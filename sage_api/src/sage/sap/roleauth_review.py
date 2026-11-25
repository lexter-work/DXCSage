"""Review of a role-authorization change request: valid, allowed by the policy, and safe for segregation of duties.
Used by the review workflow and, as its gate, by the workflow that makes the change."""
import re
from typing import Literal

from pydantic import BaseModel

from sage.policies import PolicyStatus, policy_view
from sage.sap.roles import Conflict, any_of, role_data
from sage.sap.sod import SAFE, conflicts_for_roles
from sage.tasks.sap_read_table import ReadTable, ReadTableIn

VALUE_OK = re.compile(r"^[^'\x00-\x1f]{1,40}$")        # goes into a WHERE clause: no quote or control character


class RoleChange(BaseModel):
    role: str
    action: Literal["add", "remove", "modify", "remove_tcode"]
    object: str = ""                  # not used by remove_tcode
    field: str = ""                   # not used by remove_tcode
    value: str                        # the value to add or remove, the new value of a modify, or the transaction code of remove_tcode
    current_value: str = ""           # modify only: the value being replaced


class RoleReview(BaseModel):
    role: str
    derived_children: list[str]
    conflicts_now: list[str]
    conflicts_after: list[Conflict]
    introduced: list[str]


class Violation(BaseModel):
    role: str
    object: str
    policy: str
    description: str


class Review(BaseModel):
    ready: bool
    errors: list[str]
    warnings: list[str]
    violations: list[Violation]
    changes: list[RoleChange]
    roles: list[RoleReview]
    unverified_roles: list[str]
    policies: list[PolicyStatus] = []
    next_step: str = ""


def clean(raw: list[RoleChange], max_entries: int) -> tuple[list[RoleChange], list[str]]:
    errors, seen, out = [], set(), []
    if not raw:
        errors.append("The request has no changes. Give them in the list or attach an Excel file.")
    if len(raw) > max_entries:
        errors.append(f"The request has {len(raw)} changes; the limit is {max_entries} (setting rolechange.policy).")
    for c in raw:
        c = c.model_copy(update={"role": c.role.strip().upper(), "object": c.object.strip().upper(), "field": c.field.strip().upper(),
                                 "value": c.value.strip(), "current_value": c.current_value.strip()})
        if c.action == "remove_tcode":
            c = c.model_copy(update={"object": "S_TCODE", "field": "TCD", "value": c.value.upper()})
        bad = not SAFE.match(c.role) or len(c.role) > 30 or not SAFE.match(c.object or "X") or not SAFE.match(c.field or "X") \
            or not VALUE_OK.match(c.value) or (c.current_value and not VALUE_OK.match(c.current_value))
        if bad or not c.object or not c.field:
            errors.append(f"Invalid change for role '{c.role}': give a role, object, field and value with plain characters (no quotes).")
        elif c.action == "modify" and (not c.current_value or c.current_value == c.value):
            errors.append(f"{c.role} {c.object}-{c.field}: a modify needs the current value and a different new value.")
        elif (key := (c.role, c.action, c.object, c.field, c.value, c.current_value)) not in seen:
            seen.add(key)
            out.append(c)
    for c in out:
        if c.action == "add" and any(o.action == "remove" and (o.role, o.object, o.field, o.value) == (c.role, c.object, c.field, c.value) for o in out):
            errors.append(f"{c.role} {c.object}-{c.field} = {c.value} is both added and removed in this request.")
    return out, errors


def violations(changes: list[RoleChange], policy: dict) -> list[Violation]:
    restricted = {r["object"].upper(): r.get("reason", "") for r in policy.get("restricted_objects", [])}
    allowed = set(policy.get("allowed_activity_levels", []))
    out = []
    for c in changes:
        def v(name, text):
            out.append(Violation(role=c.role, object=c.object, policy=name, description=text))
        if c.role.startswith("SAP_"):
            v("SAP standard role protection", f"{c.role} is an SAP standard role. Copy it to a Z or Y role and change the copy.")
        if c.object in restricted:
            v("Restricted authorization object", f"{c.object} is restricted: {restricted[c.object]}")
        if c.value == "*" and c.action in ("add", "modify"):
            v("Wildcard value", f"The value '*' for {c.object}-{c.field} grants unrestricted access.")
        if allowed and c.field == "ACTVT" and c.value not in allowed:
            v("Activity level allowlist", f"Activity {c.value} for {c.object} is not on the allowed list {sorted(allowed)}.")
    return out


async def _rows(ctx, table, fields, where):
    return await ctx.task(ReadTable, ReadTableIn(table=table, fields=fields, where=where))


async def review(ctx, raw: list[RoleChange], policy: dict, rules: list[dict], pre_errors: list[str] | None = None, policies: list[dict] | None = None) -> Review:
    if pre_errors:
        return Review(ready=False, errors=pre_errors, warnings=[], violations=[], changes=[], roles=[], unverified_roles=[])
    changes, errors = clean(raw, int(policy.get("max_changes_per_request", 50)))
    warnings: list[str] = []
    if errors:
        return Review(ready=False, errors=errors, warnings=warnings, violations=[], changes=changes, roles=[], unverified_roles=[])

    roles = sorted({c.role for c in changes})
    defs = {r["AGR_NAME"].strip(): r["PARENT_AGR"].strip() for r in (await _rows(ctx, "AGR_DEFINE", ["AGR_NAME", "PARENT_AGR"], any_of("AGR_NAME", roles))).rows}
    composite = {r["AGR_NAME"].strip() for r in (await _rows(ctx, "AGR_AGRS", ["AGR_NAME"], any_of("AGR_NAME", roles))).rows}
    kids: dict[str, list[str]] = {r: [] for r in roles}
    for r in (await _rows(ctx, "AGR_DEFINE", ["AGR_NAME", "PARENT_AGR"], any_of("PARENT_AGR", roles))).rows:
        kids.setdefault(r["PARENT_AGR"].strip(), []).append(r["AGR_NAME"].strip())
    for r in roles:
        if r not in defs:
            errors.append(f"Role {r} does not exist on this system.")
        elif defs[r]:
            errors.append(f"{r} is a derived role of {defs[r]}. Change the parent role and regenerate instead.")
        elif r in composite:
            errors.append(f"{r} is a composite role. Change its single roles instead.")
        elif kids.get(r):
            warnings.append(f"{r} has derived roles ({', '.join(sorted(kids[r]))}). They are regenerated after the change.")
    ok_roles = [r for r in roles if r in defs and not defs[r] and r not in composite]

    unverified, state = [], {}
    for r in ok_roles:                                  # live state of the values the request touches
        mine = [c for c in changes if c.role == r]
        objs = sorted({c.object for c in mine})
        t = await _rows(ctx, "AGR_1251", ["OBJECT", "FIELD", "LOW"], f"AGR_NAME = '{r}' AND DELETED = ' ' AND ( {any_of('OBJECT', objs)} )")
        if t.truncated:
            unverified.append(r)
        state[r] = {(x["OBJECT"].strip(), x["FIELD"].strip(), x["LOW"].strip()) for x in t.rows}
        menu = {x["TCODE"].strip() for x in (await _rows(ctx, "AGR_TCODES", ["TCODE"], f"AGR_NAME = '{r}' AND ( {any_of('TCODE', sorted({c.value for c in mine if c.action == 'remove_tcode'}))} )")).rows} \
            if any(c.action == "remove_tcode" for c in mine) else set()
        for c in mine:
            has = lambda o, f, v: (o, f, v) in state[r]  # noqa: E731
            if c.action == "add":
                if not any(o == c.object for o, _, _ in state[r]):
                    errors.append(f"{r}: {c.object} is not on the role. Adding a whole object is not supported; add it in PFCG.")
                elif has(c.object, c.field, c.value):
                    errors.append(f"{r}: {c.object}-{c.field} already has the value {c.value}.")
            elif c.action in ("remove", "modify"):
                old = c.value if c.action == "remove" else c.current_value
                if not has(c.object, c.field, old):
                    errors.append(f"{r}: {c.object}-{c.field} does not have the value {old}.")
                if c.action == "modify" and has(c.object, c.field, c.value):
                    errors.append(f"{r}: {c.object}-{c.field} already has the new value {c.value}.")
            elif not has("S_TCODE", "TCD", c.value) and c.value not in menu:
                warnings.append(f"{r}: transaction {c.value} is not in the menu or in S_TCODE as an exact value. The removal may do nothing (a pattern such as SE* is not found).")

    viols = violations([c for c in changes if c.role in ok_roles], policy)
    reviews = []
    if ok_roles:
        data, unreadable = await role_data(ctx, set(ok_roles), rules)
        unverified = sorted(set(unverified) | set(unreadable))
        for r in ok_roles:
            after = {"objects": set(data[r]["objects"]), "tcodes": set(data[r]["tcodes"]), "activities": {o: set(a) for o, a in data[r]["activities"].items()}}
            for c in (x for x in changes if x.role == r):
                gone = {"remove": c.value, "modify": c.current_value, "remove_tcode": c.value}.get(c.action, "")
                came = c.value if c.action in ("add", "modify") else ""
                for val, add in ((gone, False), (came, True)):
                    if not val:
                        continue
                    if c.object == "S_TCODE" and c.field == "TCD":
                        (after["tcodes"].add if add else after["tcodes"].discard)(val)
                    elif c.field == "ACTVT":
                        acts = after["activities"].setdefault(c.object, set())
                        (acts.add if add else acts.discard)(val)
            before_c = conflicts_for_roles(rules, [r], {r: data[r]})
            after_c = conflicts_for_roles(rules, [r], {r: after})
            ids = {x["rule_id"] for x in before_c}
            reviews.append(RoleReview(role=r, derived_children=sorted(kids.get(r, [])), conflicts_now=sorted(ids),
                                      conflicts_after=[Conflict(**x) for x in after_c], introduced=sorted({x["rule_id"] for x in after_c} - ids)))
        for rv in reviews:
            for c in rv.conflicts_after:
                if c.rule_id in rv.introduced and c.severity == "CRITICAL":
                    errors.append(f"{rv.role}: the change would add the CRITICAL conflict {c.rule_id} ({c.conflicting_objects}).")
    if unverified:
        warnings.append(f"The authorizations of {', '.join(unverified)} could not be read completely, so a conflict there may be missing.")
    if viols:
        errors.append(f"{len(viols)} policy violation(s). Such changes need an exception from the security team and are done in PFCG.")
    pol, pol_errors, step = policy_view(policies or [])
    errors += pol_errors
    return Review(ready=not errors, errors=errors, warnings=warnings, violations=viols, changes=changes, roles=reviews, unverified_roles=unverified, policies=pol, next_step=step)
