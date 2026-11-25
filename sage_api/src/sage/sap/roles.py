"""Shared reads of users, role assignments and role authorizations (RFC_READ_TABLE through the shared ReadTable task).

Every function is part of a workflow run: the calls go through ctx.task, so each read is a stored, replayable step and the
order of calls must not depend on live data other than earlier results."""
from pydantic import BaseModel

from sage.sap.sod import SAFE, sides
from sage.tasks.sap_read_table import ReadTable, ReadTableIn


class Conflict(BaseModel):
    rule_id: str
    severity: str
    roles: list[str]
    conflicting_objects: str
    rule_description: str
    recommendation: str


def any_of(field: str, values) -> str:
    return " OR ".join(f"{field} = '{v}'" for v in values)


async def existing_users(ctx, users: list[str]) -> set[str]:
    r = await ctx.task(ReadTable, ReadTableIn(table="USR02", fields=["BNAME"], where=any_of("BNAME", users)))
    return {x["BNAME"].strip() for x in r.rows}


async def assigned_roles(ctx, users: list[str], day: str) -> dict[str, list[str]]:
    """Directly assigned roles whose validity period contains `day` (YYYYMMDD)."""
    r = await ctx.task(ReadTable, ReadTableIn(table="AGR_USERS", fields=["UNAME", "AGR_NAME", "FROM_DAT", "TO_DAT"], where=any_of("UNAME", users)))
    out: dict[str, set[str]] = {u: set() for u in users}
    for x in r.rows:
        frm, to, role = x["FROM_DAT"].strip(), x["TO_DAT"].strip(), x["AGR_NAME"].strip()
        if role and (not frm or frm <= day) and (not to or to >= day):
            out.setdefault(x["UNAME"].strip(), set()).add(role)
    return {u: sorted(v) for u, v in out.items()}


async def existing_roles(ctx, roles: list[str]) -> set[str]:
    r = await ctx.task(ReadTable, ReadTableIn(table="AGR_DEFINE", fields=["AGR_NAME"], where=any_of("AGR_NAME", roles)))
    return {x["AGR_NAME"].strip() for x in r.rows}


async def with_children(ctx, roles: list[str]) -> set[str]:
    """The roles plus the single roles inside any composite role among them."""
    usable = [r for r in roles if SAFE.match(r)]
    out = set(roles)
    if usable:
        c = await ctx.task(ReadTable, ReadTableIn(table="AGR_AGRS", fields=["AGR_NAME", "CHILD_AGR"], where=any_of("AGR_NAME", usable)))
        out |= {x["CHILD_AGR"].strip() for x in c.rows if x["CHILD_AGR"].strip()}
    return out


async def role_data(ctx, roles: set[str], rules: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """What each role grants, limited to what the SoD rules mention: {role: {objects, tcodes, activities}} and the roles
    that could not be read completely (unsafe name or row cap hit)."""
    values = sorted({v for rule in rules for v, _ in sides(rule)})
    scoped = sorted({v for rule in rules for v, a in sides(rule) if a})
    wanted = (f"( {any_of('OBJECT', values)} OR "
              f"( OBJECT = 'S_TCODE' AND FIELD = 'TCD' AND ( {any_of('LOW', values)} ) ) )")
    data, unverified = {}, []
    for role in sorted(roles):
        d = {"objects": set(), "tcodes": set(), "activities": {}}
        data[role] = d
        if not SAFE.match(role):
            unverified.append(role)
            continue
        r = await ctx.task(ReadTable, ReadTableIn(table="AGR_1251", fields=["OBJECT", "FIELD", "LOW"],
                                                  where=f"AGR_NAME = '{role}' AND DELETED = ' ' AND {wanted}"))
        if r.truncated:
            unverified.append(role)
        for row in r.rows:
            obj, fld, low = row["OBJECT"].strip(), row["FIELD"].strip(), row["LOW"].strip()
            if obj == "S_TCODE" and fld == "TCD":
                d["tcodes"].add(low)
            else:
                d["objects"].add(obj)
    for role in sorted(roles):
        if not scoped or not (data[role]["objects"] & set(scoped)):
            continue
        r = await ctx.task(ReadTable, ReadTableIn(table="AGR_1251", fields=["OBJECT", "LOW"],
                                                  where=f"AGR_NAME = '{role}' AND DELETED = ' ' AND FIELD = 'ACTVT' AND ( {any_of('OBJECT', scoped)} )"))
        if r.truncated and role not in unverified:
            unverified.append(role)
        for row in r.rows:
            if row["LOW"].strip():
                data[role]["activities"].setdefault(row["OBJECT"].strip(), set()).add(row["LOW"].strip())
    return data, sorted(unverified)
