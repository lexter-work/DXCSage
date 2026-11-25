"""Free-form policy documents, and the verdicts the AI records after reading one against a request.

The structured rules (restricted objects, wildcards, activity levels) are checked by code. A policy document is prose, so it is
judged by the model in the chat: the review workflow hands it the text and a hash of the request, the model records its
findings with sap_record_policy_review, and the next review uses them. A verdict is tied to the exact text of the policy
(its fingerprint) and to the exact request (its hash), so editing either asks for a new review. The first verdict recorded for a
policy and request stands; an admin can clear it. It is an AI judgment, not an access control: the structured checks stay."""
import hashlib
import io
import json
import re
import zipfile

from typing import Literal

from pydantic import BaseModel

from sage.util import iso, utcnow

MAX_TEXT = 60_000
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}$")


class PolicyError(Exception):
    pass


class Finding(BaseModel):
    role: str = ""
    description: str


class PolicyStatus(BaseModel):
    name: str
    state: Literal["reviewed", "pending", "missing"]
    fingerprint: str = ""
    request_hash: str = ""
    kind: str = ""
    text: str = ""                       # only while the review is pending: the text the AI has to read
    findings: list[Finding] = []


def policy_view(rows: list[dict]) -> tuple[list[PolicyStatus], list[str], str]:
    """(statuses, errors, what the AI must do next) from PolicyService.status_for."""
    out, errors, pending = [], [], []
    for r in rows:
        if r.get("missing"):
            out.append(PolicyStatus(name=r["name"], state="missing"))
            errors.append(f"The policy '{r['name']}' named in the request does not exist.")
        elif r["findings"] is None:
            out.append(PolicyStatus(name=r["name"], state="pending", fingerprint=r["fingerprint"], request_hash=r["request_hash"], kind=r["kind"], text=r["text"]))
            errors.append(f"The policy '{r['name']}' has not been reviewed for this exact request yet.")
            pending.append(r["name"])
        else:
            out.append(PolicyStatus(name=r["name"], state="reviewed", fingerprint=r["fingerprint"], request_hash=r["request_hash"], kind=r["kind"],
                                    findings=[Finding(**f) for f in r["findings"]]))
            errors += [f"Policy '{r['name']}': {f['description']}" + (f" (role {f['role']})" if f.get("role") else "") for f in r["findings"]]
    step = ""
    if pending:
        step = ("POLICY REVIEW NEEDED for: " + ", ".join(pending) + ". Read the text of each pending policy in `policies` and compare it with the changes in this request. "
                "For every way the request breaks the policy, make one finding (the role, and a short description). Then call sap_record_policy_review once per pending policy "
                "with its policy_name, kind, request_hash and fingerprint exactly as given here, and your findings (an empty list when the request meets the policy). "
                "Then run this review again.")
    return out, errors, step


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def request_hash(kind: str, changes: list[dict]) -> str:
    """The same request always has the same hash, whatever the order of the changes."""
    rows = sorted(json.dumps(c, sort_keys=True) for c in changes)
    return hashlib.sha256((kind + "\n" + "\n".join(rows)).encode("utf-8")).hexdigest()[:16]


def extract_text(filename: str, data: bytes) -> str:
    """Text of a .txt, .md or .docx file. A .docx is read from its XML, so no extra library is needed."""
    low = filename.lower()
    if low.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace").strip()
    if low.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, KeyError):
            raise PolicyError("The file is not a readable .docx document.") from None
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:(tab|br)\b[^>]*/>", " ", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        return re.sub(r"&amp;", "&", re.sub(r"&lt;", "<", re.sub(r"&gt;", ">", text))).strip()
    raise PolicyError("Use a .txt, .md or .docx file, or paste the text.")


class PolicyService:
    def __init__(self, db, audit, clock=utcnow):
        self._db, self._audit, self._clock = db, audit, clock

    async def items(self) -> list[dict]:
        rows = await self._db.fetchall(
            "SELECT p.id,p.name,p.text,p.fingerprint,p.required,p.updated_by,p.updated_at,"
            "(SELECT COUNT(*) FROM policy_reviews r WHERE r.policy_name=p.name AND r.fingerprint=p.fingerprint) AS reviews FROM policies p ORDER BY p.name")
        for r in rows:
            r["required"] = bool(r["required"])
        return rows

    async def get(self, name: str) -> dict | None:
        return await self._db.fetchone("SELECT id,name,text,fingerprint,required FROM policies WHERE name=? COLLATE NOCASE", (name,))

    async def save(self, policy_id, name: str, text: str, required: bool, actor: str) -> int:
        name, text = re.sub(r"\s+", " ", name or "").strip(), (text or "").strip()
        if not NAME.match(name):
            raise PolicyError("The name uses letters, digits, spaces and - _ . and is at most 60 characters.")
        if not text or len(text) > MAX_TEXT:
            raise PolicyError(f"The policy text must be between 1 and {MAX_TEXT} characters.")
        clash = await self._db.fetchone("SELECT id FROM policies WHERE name=? COLLATE NOCASE", (name,))
        if clash and clash["id"] != policy_id:
            raise PolicyError("A policy with this name already exists.")
        now = iso(self._clock())
        if policy_id is None:
            policy_id = await self._db.execute("INSERT INTO policies(name,text,fingerprint,required,updated_by,updated_at) VALUES(?,?,?,?,?,?)",
                                               (name, text, fingerprint(text), int(required), actor, now))
        else:
            old = await self._db.fetchone("SELECT name FROM policies WHERE id=?", (policy_id,))
            await self._db.execute("UPDATE policies SET name=?, text=?, fingerprint=?, required=?, updated_by=?, updated_at=? WHERE id=?",
                                   (name, text, fingerprint(text), int(required), actor, now, policy_id))
            if old and old["name"] != name:
                await self._db.execute("DELETE FROM policy_reviews WHERE policy_name=?", (old["name"],))
        await self._audit.write("policy.save", actor, detail={"policy": name, "required": required, "fingerprint": fingerprint(text), "length": len(text)})
        return policy_id

    async def delete(self, policy_id, actor: str):
        p = await self._db.fetchone("SELECT name FROM policies WHERE id=?", (policy_id,))
        if p:
            await self._db.execute("DELETE FROM policy_reviews WHERE policy_name=?", (p["name"],))
            await self._db.execute("DELETE FROM policies WHERE id=?", (policy_id,))
            await self._audit.write("policy.delete", actor, detail={"policy": p["name"]})

    async def clear_reviews(self, policy_id, actor: str):
        p = await self._db.fetchone("SELECT name FROM policies WHERE id=?", (policy_id,))
        if p:
            await self._db.execute("DELETE FROM policy_reviews WHERE policy_name=?", (p["name"],))
            await self._audit.write("policy.clear_reviews", actor, detail={"policy": p["name"]})

    async def reviews(self, policy_id) -> list[dict]:
        rows = await self._db.fetchall(
            "SELECT r.kind,r.request_hash,r.findings,r.reviewed_by,r.created_at FROM policy_reviews r JOIN policies p ON p.name=r.policy_name AND p.fingerprint=r.fingerprint "
            "WHERE p.id=? ORDER BY r.id DESC LIMIT 100", (policy_id,))
        for r in rows:
            r["findings"] = json.loads(r["findings"])
        return rows

    async def status_for(self, names: list[str], kind: str, req_hash: str) -> list[dict]:
        """For each required policy, plus any named in the request: what the AI recorded for this exact request, or None when it must still review."""
        required = [r["name"] for r in await self._db.fetchall("SELECT name FROM policies WHERE required=1 ORDER BY name")]
        out = []
        for name in dict.fromkeys(required + [n for n in names if n]):
            p = await self.get(name)
            if p is None:
                out.append({"name": name, "missing": True})
                continue
            rev = await self._db.fetchone("SELECT findings FROM policy_reviews WHERE policy_name=? AND fingerprint=? AND kind=? AND request_hash=?",
                                          (p["name"], p["fingerprint"], kind, req_hash))
            out.append({"name": p["name"], "fingerprint": p["fingerprint"], "text": p["text"], "request_hash": req_hash, "kind": kind,
                        "findings": json.loads(rev["findings"]) if rev else None})
        return out

    async def record(self, name, fingerprint_, kind, req_hash, findings: list[dict], actor: str) -> str:
        p = await self.get(name)
        if p is None:
            raise PolicyError(f"There is no policy named '{name}'.")
        if p["fingerprint"] != fingerprint_:
            raise PolicyError("The policy text changed since the review asked for it. Run the review again and use its fingerprint.")
        clean = [{"role": str(f.get("role", ""))[:60], "description": re.sub(r"\s+", " ", str(f.get("description", ""))).strip()[:500]} for f in findings
                 if str(f.get("description", "")).strip()]
        try:
            await self._db.execute("INSERT INTO policy_reviews(policy_name,fingerprint,kind,request_hash,findings,reviewed_by,created_at) VALUES(?,?,?,?,?,?,?)",
                                   (p["name"], p["fingerprint"], kind, req_hash, json.dumps(clean), actor, iso(self._clock())))
        except Exception:  # noqa: BLE001 - the first verdict stands
            raise PolicyError("A review of this policy for this exact request is already recorded. An admin can clear it on the Policies page.") from None
        await self._audit.write("policy.review", actor, detail={"policy": p["name"], "kind": kind, "request_hash": req_hash, "findings": clean})
        return f"Recorded {len(clean)} finding(s) for policy '{p['name']}'."
