"""All configuration lives here. Defaults are seeded in code; admins change them in the UI."""
import json

from sage.util import iso

SECRET_KEYS = {"providers.anthropic_api_key", "providers.openai_api_key"}

DEFAULTS: dict = {
    "agent.max_turns": 10,
    "providers.max_tokens": 4096,
    "providers.models": {
        "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
        "openai": ["gpt-5"],
    },
    "providers.anthropic_api_key": "",
    "providers.openai_api_key": "",
    "wait.backoff": [[60, 10], [300, 60], [3600, 300], [10800, 900], [86400, 3600]],
    "wait.max_wait": 86400,
    "health.max_age": 86400,
    "sap.rowcount_cap": 5000,
    "workflows.disabled": [],
    "addon.protected_components": ["SAP_BASIS", "SAP_ABA", "SAP_GWFND", "SAP_UI", "S4CORE", "S4COREOP", "S4DEPREC", "S4FND",
                                   "EA-DFPS", "EA-PS", "FI-CAX", "SAP_BW"],
    "sod.matrix": {
        "matrix_version": "1.0.0",
        "conflicts": [
            {"id": "SOD-001", "object_1": "F_BKPF_BUK", "activity_1": "01,02", "object_2": "F_BKPF_BES",
             "description": "Posting (create or change, not display) and payment approval", "risk_level": "HIGH",
             "recommended_action": "Remove one of the conflicting objects or split into separate roles."},
            {"id": "SOD-002", "object_1": "M_BEST_BSA", "object_2": "M_BEST_EKO",
             "description": "Purchase order creation and approval", "risk_level": "CRITICAL",
             "recommended_action": "Separate PO creation from PO approval."},
            {"id": "SOD-006", "object_1": "S_DEVELOP", "object_2": "S_ADMI_FCD",
             "description": "Development access combined with system administration", "risk_level": "CRITICAL",
             "recommended_action": "Never combine development and system administration."},
        ],
    },
    "readiness.prerequisite_notes": {
        "download_wait_seconds": 600,
        "download_poll_seconds": 15,
        "require_implemented": True,
        "implementation_status": {"table": "CWBNTCUST", "field": "PRSTATUS", "implemented_values": ["E"]},
        "notes": [
            {"number": "1668882", "remark": "Latest version required."},
            {"number": "2971435", "remark": "Latest version required."},
            {"number": "2758146", "remark": "If SAP Note 2310438 was implemented previously, revert it first."},
            {"number": "2399707", "remark": "Minimum requirement for SAP Readiness Check."},
            {"number": "2903677"},
            {"number": "2502552"},
            {"number": "2827612", "conditional": True,
             "remark": "Only if ST-PI <= 2008_1_700 SP27, 2008_1_710 SP27 or 740 SP17."},
            {"number": "2781766"},
        ],
    },
}


class SettingsStore:
    def __init__(self, db, box, audit):
        self._db, self._box, self._audit = db, box, audit

    async def get(self, key):
        if key not in DEFAULTS:
            raise KeyError(key)
        row = await self._db.fetchone("SELECT value,is_secret FROM settings WHERE key=?", (key,))
        if not row:
            return DEFAULTS[key]
        return self._box.decrypt(row["value"]) if row["is_secret"] else json.loads(row["value"])

    async def set(self, key, value, actor):
        if key not in DEFAULTS:
            raise KeyError(key)
        secret = key in SECRET_KEYS
        stored = self._box.encrypt(str(value)) if secret else json.dumps(value)
        await self._db.execute(
            "INSERT INTO settings(key,value,is_secret,updated_by,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, is_secret=excluded.is_secret, "
            "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (key, stored, int(secret), actor, iso()))
        await self._audit.write("config.change", actor, detail={"key": key} if secret else {"key": key, "value": value})

    async def public(self) -> dict:
        out = {}
        for key in DEFAULTS:
            v = await self.get(key)
            out[key] = {"set": bool(v)} if key in SECRET_KEYS else v
        return out
