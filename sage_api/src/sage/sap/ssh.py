"""Optional SSH access to the host of a SAP system, for what RFC cannot reach (for example the files of SUM).

Safety rules: the server's host key must be pinned by an admin before any login, the secret is only used to log in, and
callers never pass a shell string: they use read_file / file_readable, which validate the path and quote it."""
import asyncio
import re
import shlex
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

PATH_OK = re.compile(r"^/[A-Za-z0-9_./-]{1,200}$")
MAX_BYTES = 4_000_000


class SshError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class SshParams:
    host: str
    port: int
    user: str
    auth: str            # "password" | "key"
    secret: str          # the password, or the private key (OpenSSH or PEM, no passphrase)
    host_key: str        # pinned server public key, OpenSSH line; "" = not trusted yet


@dataclass
class SshResult:
    stdout: str
    stderr: str
    code: int


def fingerprint(public_line: str) -> str:
    import asyncssh
    return asyncssh.import_public_key(public_line).get_fingerprint("sha256")


async def asyncssh_host_key(host: str, port: int) -> str:
    """The key the server presents, without logging in."""
    import asyncssh
    try:
        key = await asyncio.wait_for(asyncssh.get_server_host_key(host, port=port), 15)
    except (OSError, asyncio.TimeoutError, asyncssh.Error) as e:
        raise SshError("CONNECT", str(e) or type(e).__name__) from None
    return key.export_public_key("openssh").decode().strip()


class _Client:
    def __init__(self, conn):
        self._c = conn

    async def run(self, command: str, timeout: float) -> SshResult:
        r = await asyncio.wait_for(self._c.run(command, check=False), timeout)
        return SshResult(str(r.stdout or ""), str(r.stderr or ""), r.exit_status if r.exit_status is not None else -1)

    async def close(self):
        self._c.close()
        await self._c.wait_closed()


async def asyncssh_connector(p: SshParams) -> _Client:
    import asyncssh
    if not p.host_key:
        raise SshError("HOST_KEY", "The host key of this server is not trusted yet.")
    try:
        opts: dict[str, Any] = {"username": p.user, "known_hosts": ([asyncssh.import_public_key(p.host_key)], [], []), "agent_path": None}
        if p.auth == "key":
            opts.update(client_keys=[asyncssh.import_private_key(p.secret)], password=None)
        else:
            opts.update(password=p.secret, client_keys=None)
        return _Client(await asyncio.wait_for(asyncssh.connect(p.host, p.port, **opts), 20))
    except asyncssh.PermissionDenied:
        raise SshError("LOGIN", "The server refused the SSH user or secret.") from None
    except asyncssh.HostKeyNotVerifiable:
        raise SshError("HOST_KEY", "The server presented a different host key than the trusted one.") from None
    except (OSError, asyncio.TimeoutError, asyncssh.Error) as e:
        raise SshError("CONNECT", str(e) or type(e).__name__) from None


class SapSsh:
    def __init__(self, load_params: Callable[[int], Awaitable[SshParams | None]],
                 connector: Callable[[SshParams], Awaitable[Any]] = asyncssh_connector,
                 host_key: Callable[[str, int], Awaitable[str]] = asyncssh_host_key):
        self._load, self._connect, self.host_key = load_params, connector, host_key

    async def params(self, system_id: int) -> SshParams:
        p = await self._load(system_id)
        if p is None:
            raise SshError("NOT_SET_UP", "SSH is not set up for this system. An admin can add it on the Systems page.")
        return p

    async def _run(self, system_id: int, command: str, timeout: float = 30) -> SshResult:
        client = await self._connect(await self.params(system_id))       # shortcut: one connection per command, fine for polling; pool if it gets chatty
        try:
            return await client.run(command, timeout)
        except asyncio.TimeoutError:
            raise SshError("TIMEOUT", f"The command took longer than {timeout:g} s.") from None
        finally:
            await client.close()

    async def test(self, params: SshParams) -> None:
        client = await self._connect(params)
        try:
            await client.run("true", 15)
        finally:
            await client.close()

    async def read_file(self, system_id: int, path: str, tail_lines: int = 0) -> str:
        """Text of a file (the last `tail_lines` lines, or at most the last 4 MB)."""
        if not PATH_OK.match(path) or ".." in path:
            raise SshError("BAD_PATH", f"Not an allowed path: {path}")
        cmd = f"tail -n {int(tail_lines)} -- {shlex.quote(path)}" if tail_lines else f"tail -c {MAX_BYTES} -- {shlex.quote(path)}"
        r = await self._run(system_id, cmd)
        if r.code != 0:
            raise SshError("READ", (r.stderr.strip() or f"exit code {r.code}") + f" ({path})")
        return r.stdout

    async def file_readable(self, system_id: int, path: str) -> bool:
        if not PATH_OK.match(path) or ".." in path:
            raise SshError("BAD_PATH", f"Not an allowed path: {path}")
        return (await self._run(system_id, f"test -r {shlex.quote(path)}")).code == 0

    async def host_time(self, system_id: int) -> str:
        """The clock of the host as YYYYMMDDHHMMSS in the host's own time zone (SUM writes its times in it)."""
        r = await self._run(system_id, "date +%Y%m%d%H%M%S")
        if r.code != 0 or not re.fullmatch(r"\d{14}", r.stdout.strip()):
            raise SshError("READ", "Could not read the clock of the host.")
        return r.stdout.strip()

    async def process_running(self, system_id: int, name: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", name):
            raise SshError("BAD_PATH", f"Not an allowed process name: {name}")
        return (await self._run(system_id, f"pgrep -x -- {shlex.quote(name)}")).code == 0
