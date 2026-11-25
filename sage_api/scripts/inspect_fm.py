"""One-off diagnostic: print the real import/export/table parameter names of a function
module on a system already registered in Sage, via RFC_GET_FUNCTION_INTERFACE.

Usage (from sage_api):
    uv run python scripts/inspect_fm.py <fm_name> <system_label>
Reuses the app's own stored, encrypted RFC credentials; nothing is prompted or typed.
"""
import asyncio
import sys

from sage.services import build_services


async def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <fm_name> <system_label>")
        sys.exit(1)
    fm_name, label = sys.argv[1:3]

    svc = await build_services(data_dir=".data", key_dir=".keys")
    system = await svc.systems.by_label(label)
    if not system:
        print(f"no system registered with label {label!r}")
        sys.exit(1)

    res = await svc.rfc.call(system["id"], "RFC_GET_FUNCTION_INTERFACE", FUNCNAME=fm_name)
    for p in res["PARAMS"]:
        print(f"{p['PARAMCLASS']:6} {p['PARAMETER']:20} type={p.get('TYP', '')}")
    svc.rfc.drop(system["id"])


if __name__ == "__main__":
    asyncio.run(main())
