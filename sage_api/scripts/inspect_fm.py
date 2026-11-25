"""One-off diagnostic: print the real import/export/table parameter names of a function
module on a live SAP system, via RFC_GET_FUNCTION_INTERFACE.

Usage (from sage_api, with SAPNWRFC_HOME set in the environment):
    uv run python scripts/inspect_fm.py <fm_name> <ashost> <sysnr> <client> <user>
Password is prompted, never passed on the command line.
"""
import getpass
import os
import sys


def main():
    if len(sys.argv) != 6:
        print(f"usage: {sys.argv[0]} <fm_name> <ashost> <sysnr> <client> <user>")
        sys.exit(1)
    fm_name, ashost, sysnr, client, user = sys.argv[1:6]

    sdk_home = os.environ.get("SAPNWRFC_HOME")
    if sdk_home:
        lib_dir = os.path.join(sdk_home, "lib")
        os.add_dll_directory(lib_dir)
        os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")

    import pyrfc

    passwd = getpass.getpass(f"Password for {user}: ")
    conn = pyrfc.Connection(ashost=ashost, sysnr=sysnr, client=client, user=user, passwd=passwd)
    try:
        res = conn.call("RFC_GET_FUNCTION_INTERFACE", FUNCNAME=fm_name)
        for p in res["PARAMS"]:
            print(f"{p['PARAMCLASS']:6} {p['PARAMETER']:20} type={p.get('TYP', '')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
