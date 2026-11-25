"""Excel files a user attaches to a chat. Stored under the data directory, read only by workflows run for the same user."""
import uuid
from pathlib import Path

from sage.sap.excel_requests import KINDS, SAFE_NAME, parse
from sage.util import iso, utcnow

MAX_BYTES = 5_000_000


class UploadError(Exception):
    pass


class UploadService:
    def __init__(self, db, audit, data_dir, clock=utcnow):
        self._db, self._audit, self._dir, self._clock = db, audit, Path(data_dir) / "uploads", clock

    async def save(self, user: dict, chat_id: int, filename: str, data: bytes) -> dict:
        if not data or len(data) > MAX_BYTES:
            raise UploadError(f"The file must be between 1 byte and {MAX_BYTES // 1_000_000} MB.")
        name = SAFE_NAME.sub("_", filename.strip())[-80:] or "request.xlsx"
        if not name.lower().endswith(".xlsx") or data[:2] != b"PK":
            raise UploadError("Only .xlsx workbooks can be uploaded. Download a template from the chat.")
        parsed = parse(data)
        file_id = uuid.uuid4().hex
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{file_id}.xlsx").write_bytes(data)
        await self._db.execute("INSERT INTO uploads(id,user_id,chat_id,filename,kind,rows,errors,size,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                               (file_id, user["id"], chat_id, name, parsed["kind"] or "", len(parsed["rows"]), len(parsed["errors"]), len(data), iso(self._clock())))
        await self._audit.write("upload.save", user["username"], detail={"file_id": file_id, "filename": name, "kind": parsed["kind"], "rows": len(parsed["rows"]), "size": len(data)})
        return {"id": file_id, "filename": name, "kind": parsed["kind"], "kind_title": KINDS[parsed["kind"]]["title"] if parsed["kind"] else None,
                "rows": len(parsed["rows"]), "errors": parsed["errors"][:5], "error_count": len(parsed["errors"])}

    async def info(self, file_id: str, user_id: int) -> dict | None:
        return await self._db.fetchone("SELECT * FROM uploads WHERE id=? AND user_id=?", (file_id, user_id))

    async def read(self, file_id: str, user_id: int) -> bytes:
        """The bytes of an upload of this user. Raises UploadError for an unknown file or one of somebody else."""
        if not await self.info(file_id, user_id):
            raise UploadError("That file was not found. Attach the file again.")
        return (self._dir / f"{file_id}.xlsx").read_bytes()
