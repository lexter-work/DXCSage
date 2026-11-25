"""Review of a user-role change request: are the changes valid, and would they create a segregation-of-duties conflict?
Used by the review workflow and, as its gate, by the workflow that makes the change."""
from typing import Literal

from pydantic import BaseModel

from sage.sap.roles import Conflict, assigned_roles, existing_roles, existing_users, role_data, with_children
from sage.sap.sod import SAFE, conflicts_for_roles


class Change(BaseModel):
    username: str
    role: str
    action: Literal["assign", "unassign"]


class UserReview(BaseModel):
    username: str
    roles_now: list[str]
    roles_after: list[str]
    conflicts_now: list[str]                 # rule ids
    conflicts_after: list[Conflict]
    introduced: list[str]                    # rule ids the change adds


class Review(BaseModel):
    ready: bool
    errors: list[str]
    warnings: list[str]
    changes: list[Change]                    # cleaned: upper case, duplicates removed, no-ops dropped
    users: list[UserReview]
    unverified_roles: list[str]


def clean(raw: list[Change], max_entries: int) -> tuple[list[Change], list[str]]:
    errors, pairs = [], {}
    if not raw:
        errors.append("The request has no changes.")
    if len(raw) > max_entries:
        errors.append(f"The request has {len(raw)} changes; the limit is {max_entries} (setting rolechange.max_entries).")
    for c in raw:
        u, r = c.username.strip().upper(), c.role.strip().upper()
        if not SAFE.match(u) or len(u) > 12 or not SAFE.match(r) or len(r) > 30:
            errors.append(f"Invalid user or role name: '{c.username}' / '{c.role}'.")
        else:
            pairs.setdefault((u, r), set()).add(c.action)
    out = []
    for (u, r), acts in sorted(pairs.items()):
        if len(acts) > 1:
            errors.append(f"{u} / {r} is both assigned and unassigned in this request.")
        else:
            out.append(Change(username=u, role=r, action=next(iter(acts))))
    return out, errors


async def review(ctx, raw: list[Change], rules: list[dict], day: str, max_entries: int) -> Review:
    changes, errors = clean(raw, max_entries)
    warnings: list[str] = []
    if errors or not changes:
        return Review(ready=False, errors=errors, warnings=warnings, changes=changes, users=[], unverified_roles=[])

    users = sorted({c.username for c in changes})
    have_user = await existing_users(ctx, users)
    errors += [f"User {u} does not exist on this system." for u in users if u not in have_user]
    have_role = await existing_roles(ctx, sorted({c.role for c in changes}))
    for c in changes:
        if c.role not in have_role:
            (errors if c.action == "assign" else warnings).append(f"Role {c.role} does not exist on this system ({c.action} {c.username}).")
    live = [u for u in users if u in have_user]
    if not live:
        return Review(ready=False, errors=errors, warnings=warnings, changes=changes, users=[], unverified_roles=[])

    now = await assigned_roles(ctx, live, day)
    real, after = [], {u: set(now[u]) for u in live}
    for c in changes:
        if c.username not in have_user or (c.action == "assign" and c.role not in have_role):
            continue
        held = c.role in now[c.username]
        if (c.action == "assign") == held:
            warnings.append(f"{c.username} {'already has' if held else 'does not have'} {c.role}: nothing to do.")
            continue
        real.append(c)
        (after[c.username].add if c.action == "assign" else after[c.username].discard)(c.role)

    expanded = {}
    for u in live:
        expanded[(u, "now")] = await with_children(ctx, sorted(now[u]))
        expanded[(u, "after")] = await with_children(ctx, sorted(after[u]))
    every = set().union(*expanded.values())
    rdata, unverified = await role_data(ctx, every, rules)
    rows = []
    for u in live:
        before = conflicts_for_roles(rules, sorted(expanded[(u, "now")]), rdata)
        later = conflicts_for_roles(rules, sorted(expanded[(u, "after")]), rdata)
        ids = {c["rule_id"] for c in before}
        rows.append(UserReview(username=u, roles_now=sorted(now[u]), roles_after=sorted(after[u]), conflicts_now=sorted(ids),
                               conflicts_after=[Conflict(**c) for c in later], introduced=sorted({c["rule_id"] for c in later} - ids)))
    if unverified:
        warnings.append(f"The authorizations of {', '.join(unverified)} could not be read completely, so a conflict there may be missing.")
    for r in rows:
        for c in r.conflicts_after:
            if c.rule_id in r.introduced and c.severity == "CRITICAL":
                errors.append(f"{r.username}: the change would add the CRITICAL conflict {c.rule_id} ({c.conflicting_objects}).")
    return Review(ready=not errors, errors=errors, warnings=warnings, changes=real, users=rows, unverified_roles=unverified)
