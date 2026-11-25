"""Documentation of the custom ABAP objects an admin must create on each SAP system.

Written with the fixed object IDs. `object_doc` shows one system's names instead (see systems.abap_names).
The ABAP code is in static/abap/<ID>.<part>.abap, cut from the original specs in static/rfc/.
"""
from pathlib import Path

_DIR = Path(__file__).parent / "static" / "abap"
GROUP = "ZFG_MCPARCHPH"

_REMOTE = "Attributes tab: set Processing type to Remote-Enabled Module."
_BY_VALUE = "Tick Pass Value on every parameter: RFC cannot pass a reference across the network."


def _fm_steps(oid, short, include_step=None):
    steps = [
        {"title": f"Create the function group {GROUP} if it does not exist",
         "text": f"SE80 > Function group {GROUP}. Short text: Custom RFC utilities for Sage. All Sage function modules share this one group, so create it once per system."},
    ]
    if include_step:
        steps.append(include_step)
    steps += [
        {"title": f"Create the function module {oid}",
         "text": f"SE37 > {oid}, function group {GROUP}, short text: {short}. {_REMOTE}"},
        {"title": "Define the interface", "text": f"Enter the parameters from the Interface tab on the Import, Export and Exceptions tabs. {_BY_VALUE}"},
        {"title": "Paste the code and activate",
         "text": "Paste only the code from the Function module body part, below the generated FUNCTION line, then activate."},
    ]
    return steps


def _p(name, typ, optional=False, note=""):
    return {"name": name, "type": typ, "optional": optional, "note": note}


CATALOG: dict[str, dict] = {
    "ZFG_MCPARCHPH": {
        "kind": "function_group",
        "title": "Function group for all Sage function modules",
        "summary": "The one function group that holds every custom function module and the local classes Sage uses. Create it first.",
        "flow": [
            {"title": "Holds the function modules", "text": "ZFM_RC_START_ANALYSIS, ZFM_RC_FETCH_ANALYSIS, ZFM_RC_NOTES_DOWNLOAD, ZFM_CHECK_JOB_STATUS and ZFM_AUTH_REQ_LIST live in it."},
            {"title": "Holds the local classes", "text": "The notes download and the authorization scan keep their logic in local classes. Each class sits in its own include of the group."},
            {"title": "One S_RFC value covers all", "text": "Granting S_RFC for the group name lets the RFC user call every function module in it."},
        ],
        "interface": None,
        "create": [
            {"title": "Create the group", "text": f"SE80 > Function group > {GROUP}. Short text: Custom RFC utilities for Sage. Save as local object ($TMP) or in your transport request."},
            {"title": "Activate it", "text": "Activate the group so the main program exists. The function modules and includes are added later by their own guides."},
            {"title": "Never create a group per workflow", "text": "Reuse this one. The authorization requests and the health checks assume this name."},
        ],
        "parts": [],
        "notes": ["Local classes are added as includes next to the main program. Each function module guide says which include to add."],
    },
    "ZFM_RC_START_ANALYSIS": {
        "kind": "function_module",
        "title": "Start the Readiness Check data collection",
        "summary": "Remote-enabled wrapper that schedules RC_COLLECT_ANALYSIS_DATA as an immediate background job. JOB_OPEN, JOB_SUBMIT and JOB_CLOSE cannot be called over RFC, but a function module that calls them inside the system can.",
        "flow": [
            {"title": "Receive the job name and the variant", "text": "Sage sends JOBNAME and VARIANT. The report name is fixed in the code and is not a parameter, so the module can schedule only this one report."},
            {"title": "Check S_BTCH_JOB", "text": "AUTHORITY-CHECK S_BTCH_JOB with JOBACTION = RELE. When it fails, the module raises NO_AUTHORIZATION."},
            {"title": "JOB_OPEN", "text": "Creates the background job and returns its job count. Failure raises JOB_OPEN_FAILED."},
            {"title": "JOB_SUBMIT", "text": "Adds the step: report RC_COLLECT_ANALYSIS_DATA with the given variant. Failure raises JOB_SUBMIT_FAILED."},
            {"title": "JOB_CLOSE with start immediately", "text": "Releases the job so it starts at once. Failure raises JOB_CLOSE_FAILED."},
            {"title": "Return the job name and count", "text": "REAL_JOBNAME and JOBCOUNT go back to Sage. Sage then polls the job through ZFM_CHECK_JOB_STATUS."},
        ],
        "interface": {
            "importing": [_p("JOBNAME", "BTCJOB"), _p("VARIANT", "RALDB-VARIANT", note="The report has mandatory selection fields, so a blank variant always fails.")],
            "exporting": [_p("REAL_JOBNAME", "BTCJOB", True), _p("JOBCOUNT", "BTCJOBCNT", True)],
            "exceptions": ["JOB_OPEN_FAILED", "JOB_SUBMIT_FAILED", "JOB_CLOSE_FAILED", "NO_AUTHORIZATION"],
        },
        "create": _fm_steps("ZFM_RC_START_ANALYSIS", "Schedule RC_COLLECT_ANALYSIS_DATA as an immediate background job"),
        "parts": [{"label": "Function module body", "file": "ZFM_RC_START_ANALYSIS.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": [
            "Not confirmed: the JOB_SUBMIT signature on your release. Compare it with the interface in SE37 before you activate.",
            "Not confirmed: your security team may scope S_BTCH_JOB differently. Adjust the AUTHORITY-CHECK if it must be narrower.",
            "Test in SE37 (F8) with a real variant of RC_COLLECT_ANALYSIS_DATA. Then check the job in SM37.",
        ],
    },
    "ZFM_CHECK_JOB_STATUS": {
        "kind": "function_module",
        "title": "Read the status of a background job",
        "summary": "Remote-enabled wrapper around BP_JOB_STATUS_GET. Shared: any workflow that starts a background job can poll it through this one module.",
        "flow": [
            {"title": "Receive the job name and count", "text": "Sage sends JOBNAME and JOBCOUNT, which identify one job in TBTCO."},
            {"title": "Call BP_JOB_STATUS_GET", "text": "The standard module reads the job. When it finds no job, the module raises JOB_NOT_FOUND."},
            {"title": "Return the status character", "text": "STATUS is the one-letter job status (A, F, R, S and so on). Sage maps it to a readable label."},
        ],
        "interface": {
            "importing": [_p("JOBNAME", "BTCJOB"), _p("JOBCOUNT", "BTCJOBCNT")],
            "exporting": [_p("STATUS", "BTCSTATUS", True)],
            "exceptions": ["JOB_NOT_FOUND"],
        },
        "create": [
            {"title": "Test BP_JOB_STATUS_GET first", "text": "SE37 > BP_JOB_STATUS_GET > F8. If Sage can call it directly over RFC, you do not need this module. Create it only when the direct call fails with CALL_FUNCTION_NOT_REMOTE."},
            *_fm_steps("ZFM_CHECK_JOB_STATUS", "Read TBTCO status for one background job"),
        ],
        "parts": [{"label": "Function module body", "file": "ZFM_CHECK_JOB_STATUS.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": ["Not confirmed on a live system: the status mapping, and whether your release returns more than STATUS."],
    },
    "ZFM_RC_FETCH_ANALYSIS": {
        "kind": "function_module",
        "title": "Download the Readiness Check archive",
        "summary": "Returns the finished analysis ZIP straight over RFC. The SAP GUI download step has no RFC equivalent, so the module reads the same archive from the buffered result instead.",
        "flow": [
            {"title": "Receive the job name and count", "text": "They are on the interface so the caller always says which run it means. The code does not use them yet: the system keeps one current result."},
            {"title": "Read the buffered result", "text": "CL_RC_COLLECT_CLIENT_HANDLER=>SELECT_W_CLT_CONSIDRATION reads the ZIP that RC_COLLECT_ANALYSIS_DATA saved, with fixed TRIGID, TRIGOFFSET and SUBID values."},
            {"title": "Check that the archive exists", "text": "An empty XTEXT means no finished result. The module raises ARCHIVE_NOT_FOUND."},
            {"title": "Build the file name", "text": "RC_ANALYSIS_<SID>_<date>.zip."},
            {"title": "Return the file name and the ZIP", "text": "ZIP_DATA is an XSTRING with the whole archive."},
        ],
        "interface": {
            "importing": [_p("JOBNAME", "BTCJOB"), _p("JOBCOUNT", "BTCJOBCNT")],
            "exporting": [_p("FILENAME", "STRING", True), _p("ZIP_DATA", "XSTRING", True, "Use the Export tab, not Tables: XSTRING is not a flat type.")],
            "exceptions": ["ARCHIVE_NOT_FOUND", "ARCHIVE_BUILD_NOT_IMPLEMENTED (old, no longer raised)", "NO_AUTHORIZATION (only if you add a check)"],
        },
        "create": _fm_steps("ZFM_RC_FETCH_ANALYSIS", "Return the Readiness Check ZIP archive directly over RFC"),
        "parts": [{"label": "Function module body", "file": "ZFM_RC_FETCH_ANALYSIS.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": [
            "TRIGOFFSET 999991810 was read in the debugger on one system (TS3). It may differ on another system or after a new collection run. If you get ARCHIVE_NOT_FOUND, find the value again: set a breakpoint on CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD, run the report, and read the values in the call stack.",
            "Test in SE37 (F8) only after at least one Readiness Check run has finished on the system.",
        ],
    },
    "ZFM_RC_NOTES_DOWNLOAD": {
        "kind": "function_module",
        "title": "Download missing SAP Notes",
        "summary": "Schedules the standard SNOTE download job for a list of notes. SCWN_NOTES_DOWNLOAD needs a dialog, so the module uses CL_SCWN_DARK_API=>SCHEDULE_DOWNLOAD, which runs as a background job. It only downloads: implementing a note stays a manual SNOTE step.",
        "flow": [
            {"title": "Receive the notes", "text": "IT_NOTES lists the note numbers (and versions) that CWBNTHEAD does not contain. IV_DESCRIPTION is optional."},
            {"title": "Clean the list", "text": "The class removes empty and duplicate rows."},
            {"title": "Check S_BTCH_JOB", "text": "JOBACTION = RELE and JOBGROUP = *. On failure the module returns an error message in ET_RETURN."},
            {"title": "Schedule the download", "text": "CL_SCWN_DARK_API=>SCHEDULE_DOWNLOAD creates the standard job R_SCWN_DARK_NOTES_DOWNLOAD. No COMMIT WORK, as the standard UI does not issue one."},
            {"title": "Return ids and messages", "text": "EV_SCHEDULE_ID, EV_RUN_ID and EV_JOB_COUNT identify the job. ET_RETURN carries messages. Sage then waits until the notes appear in CWBNTHEAD."},
        ],
        "interface": {
            "importing": [_p("IT_NOTES", "CWB_T_NOTE"), _p("IV_DESCRIPTION", "TEXT80", True)],
            "exporting": [_p("EV_SCHEDULE_ID", "CWBSCHLD"), _p("EV_RUN_ID", "CWBRUN_ID"), _p("EV_JOB_COUNT", "BTCJOBCNT"), _p("ET_RETURN", "BAPIRET2_T")],
            "exceptions": [],
        },
        "create": [
            {"title": f"Create the function group {GROUP} if it does not exist", "text": "See the function group guide."},
            {"title": "Create the include for the local class", "text": f"Create include LZFG_MCPARCHPHRCC and add INCLUDE LZFG_MCPARCHPHRCC. to the main program of {GROUP}, next to the other class includes. Skip this when the include exists."},
            {"title": "Paste the local class and activate", "text": "Paste the Local class part into LZFG_MCPARCHPHRCC, then activate. A local class needs no class text elements."},
            {"title": "Create the function module ZFM_RC_NOTES_DOWNLOAD", "text": f"SE37, function group {GROUP}. {_REMOTE}"},
            {"title": "Define the interface", "text": f"Use the Interface tab. {_BY_VALUE}"},
            {"title": "Paste the body and activate", "text": "Keep the body to these few lines. A longer single-module version once failed the syntax check on one system, so the logic stays in the class."},
        ],
        "parts": [
            {"label": "Local class", "file": "ZFM_RC_NOTES_DOWNLOAD.class.abap", "where": "Include LZFG_MCPARCHPHRCC"},
            {"label": "Function module body", "file": "ZFM_RC_NOTES_DOWNLOAD.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"},
        ],
        "notes": [
            "Not run yet. After the first call, check SM37 for the job NOTES_NTDWLD_<run id> and confirm it was released.",
            "Not confirmed: the S_BTCH_JOB fields. Check them in SU21.",
            "SNOTE downloads must already work for dialog users on the system (download service or technical user), or the job fails.",
        ],
    },
    "ZFM_RR_TC_OBS_START": {
        "kind": "function_module",
        "title": "Start the obsolete transaction scan",
        "summary": "Remote-enabled wrapper that schedules PROFGEN_CORR_REPORT_2 (SU25 step 2D, editing of obsolete transactions in role menus) as an immediate background job. The report name is fixed in the code, so the module can start only this one report.",
        "flow": [
            {"title": "Receive the job name", "text": "Sage sends JOBNAME. VARIANT is optional: a blank variant runs the report for all roles."},
            {"title": "Check S_BTCH_JOB", "text": "AUTHORITY-CHECK S_BTCH_JOB with JOBACTION = RELE. On failure the module raises NO_AUTHORIZATION."},
            {"title": "JOB_OPEN, JOB_SUBMIT, JOB_CLOSE", "text": "Creates the job, adds PROFGEN_CORR_REPORT_2 as its step and releases it to start at once. Each step has its own exception: JOB_OPEN_FAILED, JOB_SUBMIT_FAILED, JOB_CLOSE_FAILED."},
            {"title": "Return the job name and count", "text": "Sage polls the job with ZFM_CHECK_JOB_STATUS, then reads the result with ZFM_RR_TC_OBS_FETCH."},
            {"title": "The report checks more inside the job", "text": "PROFGEN_CORR_REPORT_2 checks S_USER_AGR (ACTVT 03) itself. Without it the job finishes with no result list, and the job log in SM37 says the user is not authorized for PFCG. S_BTCH_ADM (BTCADMIN = Y) is also checked inside JOB_OPEN and JOB_CLOSE."},
        ],
        "interface": {
            "importing": [_p("JOBNAME", "BTCJOB"), _p("VARIANT", "RALDB-VARIANT", True, "Default ' '. Blank runs all roles.")],
            "exporting": [_p("REAL_JOBNAME", "BTCJOB", True), _p("JOBCOUNT", "BTCJOBCNT", True)],
            "exceptions": ["JOB_OPEN_FAILED", "JOB_SUBMIT_FAILED", "JOB_CLOSE_FAILED", "NO_AUTHORIZATION"],
        },
        "create": _fm_steps("ZFM_RR_TC_OBS_START", "Schedule PROFGEN_CORR_REPORT_2 (SU25 2D) as an immediate background job"),
        "parts": [{"label": "Function module body", "file": "ZFM_RR_TC_OBS_START.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": [
            "Confirmed on one system (TS3): the report runs in the background with a blank selection screen.",
            "Not confirmed: whether JOB_SUBMIT also needs print parameters (PRI_PARAMS, an output device such as LP01) on your system. Test in SE37 (F8) and check SM37 and SP01 for a spool.",
            "Ask for S_USER_AGR (ACTVT 03, ACT_GROUP *) and S_BTCH_ADM (BTCADMIN Y) for the RFC user before the first run. The health check lists them under Authorizations.",
        ],
    },
    "ZFM_RR_TC_OBS_FETCH": {
        "kind": "function_module",
        "title": "Read the obsolete transaction result",
        "summary": "Reads the spool of the finished PROFGEN_CORR_REPORT_2 job and returns its text lines. Reading a spool normally needs the XBP interface, so the module calls RSPO_RETURN_ABAP_SPOOLJOB inside SAP instead.",
        "flow": [
            {"title": "Receive the job name and count", "text": "Sage sends JOBNAME and JOBCOUNT of the finished job."},
            {"title": "Find the spool request", "text": "Reads TBTCP (step 1 of the job) for LISTIDENT. When there is none, the module raises JOB_NOT_FOUND."},
            {"title": "Convert the spool number", "text": "LISTIDENT is CHAR 20 but RSPO_RETURN_ABAP_SPOOLJOB wants TSP01-RQIDENT (numeric). The module converts it first. Passing it as is dumps with CALL_FUNCTION_CONFLICT_TYPE."},
            {"title": "Read the spool text", "text": "RSPO_RETURN_ABAP_SPOOLJOB fills BUFFER, which the module passes straight into LISTLINES. A read error raises SPOOL_READ_FAILED."},
            {"title": "Return the lines", "text": "An empty list raises NO_SPOOL_FOUND. Otherwise SPOOLNUM and LISTLINES go back. Sage splits each line at the pipe characters and keeps the rows marked 'Old entry will be deleted'."},
        ],
        "interface": {
            "importing": [_p("JOBNAME", "BTCJOB"), _p("JOBCOUNT", "BTCJOBCNT")],
            "exporting": [_p("SPOOLNUM", "TSP01-RQIDENT", True),
                          _p("LISTLINES", "SOLI_TAB", False, "Define it on the Tables tab, not Export. STRING tables are not allowed in RFC, and local types are not accepted. SOLI_TAB is a standard flat table type with 255-character lines.")],
            "exceptions": ["JOB_NOT_FOUND", "NO_SPOOL_FOUND", "SPOOL_READ_FAILED"],
        },
        "create": _fm_steps("ZFM_RR_TC_OBS_FETCH", "Read a finished PROFGEN_CORR_REPORT_2 job's spool content (NO XBP)"),
        "parts": [{"label": "Function module body", "file": "ZFM_RR_TC_OBS_FETCH.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": [
            "Tested on one system (TS3): 7,329 lines came back. The line format is pipe-delimited with fixed-width fields. A row with a successor transaction filled in has not been seen, so the parser reads only role and old transaction.",
            "RSPO_R_RDI_GET_SPOOL_JOB_ITEM and EPS_GET_SPOOL_LIST do not exist on that system. Do not try them.",
            "Test in SE37 (F8) with the job name and count of a finished scan job.",
        ],
    },
    "ZFM_RR_ROLE_AUTH_CHANGE": {
        "kind": "function_module",
        "title": "Add and remove authorization values on a role",
        "summary": "Remote-enabled wrapper that drives PFCG's own PRGN_* function modules to delete and add authorization values on one role, then regenerates the profile. It never writes the authorization tables directly. WRITES to SAP: create and test it in a sandbox client first.",
        "flow": [
            {"title": "Receive the role and the values", "text": "ACTIVITY_GROUP is the role. AUTHORIZATION_VALUES are values to add and AUTHORIZATION_VALUES_DELETE are values to remove, each row with OBJECT, FIELD, LOW and HIGH. A change of a value is a delete plus an add in one call."},
            {"title": "Check S_USER_AGR and that the role exists", "text": "AUTHORITY-CHECK S_USER_AGR with ACTVT 02 and ACT_GROUP = the role (NO_AUTHORIZATION), then a read of AGR_DEFINE (ROLE_NOT_FOUND)."},
            {"title": "Lock the role", "text": "PRGN_ACTIVITY_GROUP_ENQUEUE. A foreign lock raises ROLE_LOCKED."},
            {"title": "Back up the role", "text": "PRGN_DOWNLOAD_AGR fills ROLE_BACKUP in memory. It is a snapshot, not an automatic rollback."},
            {"title": "Read the role's authorization data", "text": "PRGN_CLEAR_BUFFER, then PRGN_1250_READ_AUTH_DATA and PRGN_1251_READ_FIELD_VALUES."},
            {"title": "Check everything before any write", "text": "A bad request raises and changes nothing: OBJECT_NOT_ON_ROLE, FIELD_NOT_ON_AUTH, VALUE_NOT_FOUND (a delete that matches nothing) or VALUE_ALREADY_EXISTS (a duplicate add). The role is unlocked on every failure path."},
            {"title": "Apply in memory, then save", "text": "Deletes first, then adds (a removed value is dropped, not flagged DELETED, which PFCG would show as Inactive). PRGN_1251_SAVE_FIELD_VALUES and PRGN_1250_SAVE_AUTH_DATA only fill the buffers."},
            {"title": "Write the database", "text": "PRGN_UPDATE_DATABASE flushes the buffers to AGR_1250 and AGR_1251 and commits. From here the change is in the database."},
            {"title": "Regenerate the profile and unlock", "text": "PRGN_AUTO_GENERATE_PROFILE_NEW, then PRGN_ACTIVITY_GROUP_DEQUEUE. If generation fails, the role is changed but its profile is stale (PROFILE_GENERATION_FAILED); RETURN carries the generator's messages."},
        ],
        "interface": {
            "importing": [_p("ACTIVITY_GROUP", "AGR_NAME")],
            "exporting": [
                _p("AUTHORIZATION_VALUES", "ZROLE_AUTH_VALUE", True, "Tables tab. Values to add."),
                _p("AUTHORIZATION_VALUES_DELETE", "ZROLE_AUTH_VALUE", True, "Tables tab. Values to remove."),
                _p("ROLE_BACKUP", "TRTAB", True, "Tables tab. Snapshot made by PRGN_DOWNLOAD_AGR."),
                _p("RETURN", "BAPIRET2", True, "Tables tab. Generator messages on failure."),
            ],
            "exceptions": ["ROLE_NOT_FOUND", "UPDATE_FAILED", "NO_AUTHORIZATION", "PROFILE_GENERATION_FAILED", "ROLE_LOCKED", "BACKUP_FAILED",
                           "OBJECT_NOT_ON_ROLE", "FIELD_NOT_ON_AUTH", "VALUE_NOT_FOUND", "VALUE_ALREADY_EXISTS"],
        },
        "create": [
            {"title": "Create the structure ZROLE_AUTH_VALUE", "text": "SE11 > Structure. Short text: One authorization value (role auth add/remove). Components, typing method Types, each with a data element: OBJECT XUOBJECT, FIELD TPRFIELD, LOW XUVAL, HIGH XUVAL. If a data element is missing on your release, use a predefined type: OBJECT CHAR 10, FIELD CHAR 10, LOW CHAR 40, HIGH CHAR 40. Activate it."},
            *_fm_steps("ZFM_RR_ROLE_AUTH_CHANGE", "Add/remove PFCG role authorization values (RFC-callable)"),
        ],
        "parts": [{"label": "Function module body", "file": "ZFM_RR_ROLE_AUTH_CHANGE.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"}],
        "notes": [
            "The PRGN_* function modules are not released by SAP and may change between releases and support packages. Pin and re-test per target system.",
            "Tested on one system only (S/4HANA 2023, SAP_BASIS 758) in a sandbox client, on one role. Have your ABAP and Basis team review it, and test in a sandbox or development client first, never first in production.",
            "Never triggered during testing: ROLE_NOT_FOUND, UPDATE_FAILED and BACKUP_FAILED. PROFILE_GENERATION_FAILED was seen once without a known cause.",
            "Not handled: organization-level fields (AGR_1252), adding a whole new authorization object to a role, and the transport request of transportable roles (captured but not used).",
            "The role needs S_USER_AGR with ACTVT 02. The RFC user also needs the authorizations for profile generation.",
        ],
    },
    "ZFM_RR_TCODE_REMOVE": {
        "kind": "function_module",
        "title": "Remove a transaction code from a role",
        "summary": "Removes one transaction code from a role's menu and from its exact values in the nine transaction-code authorization objects, then regenerates the profile. Used by the role authorization change workflow for remove_tcode changes. WRITES to SAP.",
        "flow": [
            {"title": "Receive the role and the transaction", "text": "IV_ROLE_NAME, IV_TCODE. IV_TEST_RUN = X only reports the menu entry and the value count and changes nothing. IV_REQUEST is an optional transport."},
            {"title": "Refuse roles that cannot be changed this way", "text": "SAP_* standard roles, composite roles and derived child roles are rejected."},
            {"title": "Remove the menu entry", "text": "PRGN_RFC_DELETE_TRANSACTION removes the entry from AGR_TCODES. This is committed before the next step."},
            {"title": "Remove the exact values", "text": "PRGN_1250 and PRGN_1251 read and save, then PRGN_UPDATE_DATABASE, remove the exact tcode values from the nine tcode objects."},
            {"title": "Regenerate the profile", "text": "PRGN_AUTO_GENERATE_PROFILE_NEW. If the tcode was the only value of S_TCODE, the authorization is left inactive, not '*'."},
            {"title": "Return a result type", "text": "EV_RETURN_TYPE: S removed; W not found anywhere, or removed but still granted by a pattern such as SE*; E failed (running again is safe). EV_REMOVED_COUNT is the number of values removed."},
        ],
        "interface": {
            "importing": [_p("IV_ROLE_NAME", "AGR_NAME"), _p("IV_TCODE", "SYTCODE"), _p("IV_TEST_RUN", "CHAR1", True, "Default space."), _p("IV_REQUEST", "TRKORR", True)],
            "exporting": [_p("EV_RETURN_TYPE", "BAPI_MTYPE"), _p("EV_RETURN_MSG", "BAPI_MSG"), _p("EV_TRANSPORT", "TRKORR"), _p("EV_REMOVED_COUNT", "INT4"), _p("ET_RETURN", "BAPIRET2_T")],
            "exceptions": [],
        },
        "create": [
            {"title": "Work in the package of the function group", "text": f"Use the Z package that holds {GROUP}, not $TMP, so every object lands on one transport. Do not create the group again."},
            {"title": "Create the include for the local classes", "text": f"Create include LZFG_MCPARCHPHRRC in {GROUP} and paste the Local classes part into it. It holds lcx_rr_error, lcl_rr_derived_regen and lcl_rr_tcode_removal."},
            {"title": "Add one INCLUDE line to the top include", "text": f"In LZFG_MCPARCHPHTOP add: INCLUDE lzfg_mcparchphrrc. Then activate the function group. A syntax error in the include shows up here."},
            {"title": "Create the function module ZFM_RR_TCODE_REMOVE", "text": f"SE37, function group {GROUP}. {_REMOTE}"},
            {"title": "Define the interface", "text": f"Use the Interface tab. {_BY_VALUE} The module has no classic exceptions, because pyrfc would turn them into one error for the whole call."},
            {"title": "Paste the body and activate", "text": "Paste the Function module body part and activate."},
        ],
        "parts": [
            {"label": "Local classes", "file": "ZFM_RR_LOCAL_CLASSES.class.abap", "where": "Include LZFG_MCPARCHPHRRC (shared with ZFM_RR_DERIVED_REGENERATE)"},
            {"label": "Function module body", "file": "ZFM_RR_TCODE_REMOVE.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"},
        ],
        "notes": [
            "The source is final but was not yet activated or run on a live system. The signatures of the standard modules were checked on one system.",
            "Steps 2 and 3 use SAP-internal PRGN_* modules (not released). Re-test after every support package.",
            "Not all-or-nothing: the menu removal is committed before the authorization cleanup. If locking, saving or generation fails you get E and a run-again message. Running again is safe.",
            "Test on a copy of a test role: first with IV_TEST_RUN = X, then a role with two or more transactions, then a role where it is the only transaction (the least certain step), then a role with a pattern such as SE*.",
        ],
    },
    "ZFM_RR_DERIVED_REGENERATE": {
        "kind": "function_module",
        "title": "Regenerate the derived roles of a parent role",
        "summary": "After a parent role changed, regenerates every derived child role so it inherits the change. Same as PFCG > Authorizations > Adjust derived > Generate. WRITES to SAP.",
        "flow": [
            {"title": "Receive the parent role", "text": "IV_ROLE_NAME. IV_TEST_RUN = X lists the children and changes nothing. IV_REQUEST is an optional transport."},
            {"title": "Check authorizations", "text": "The class checks S_USER_AGR with ACTVT 02 on the parent and on every derived role."},
            {"title": "Regenerate each child", "text": "PRGN_RFC_CREATE_DERIVATION once per derived role, with adjust_auths, profile_gen and no_dialog set."},
            {"title": "Return a result type", "text": "S: all children done. W: the role has no derived roles. E: invalid, not authorized, or any child failed. W is never returned after a partial failure."},
        ],
        "interface": {
            "importing": [_p("IV_ROLE_NAME", "AGR_NAME"), _p("IV_TEST_RUN", "CHAR1", True, "Default space."), _p("IV_REQUEST", "TRKORR", True)],
            "exporting": [_p("EV_RETURN_TYPE", "BAPI_MTYPE"), _p("EV_RETURN_MSG", "BAPI_MSG"), _p("EV_TRANSPORT", "TRKORR"), _p("ET_RETURN", "BAPIRET2_T")],
            "exceptions": [],
        },
        "create": [
            {"title": "Create the local classes first", "text": "The classes are shared with ZFM_RR_TCODE_REMOVE. If you did not create include LZFG_MCPARCHPHRRC yet, follow the steps of that function module first."},
            {"title": "Create the function module ZFM_RR_DERIVED_REGENERATE", "text": f"SE37, function group {GROUP}. {_REMOTE}"},
            {"title": "Define the interface", "text": f"Use the Interface tab. {_BY_VALUE} No classic exceptions."},
            {"title": "Paste the body and activate", "text": "Paste the Function module body part and activate."},
        ],
        "parts": [
            {"label": "Local classes", "file": "ZFM_RR_LOCAL_CLASSES.class.abap", "where": "Include LZFG_MCPARCHPHRRC (shared with ZFM_RR_TCODE_REMOVE)"},
            {"label": "Function module body", "file": "ZFM_RR_DERIVED_REGENERATE.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"},
        ],
        "notes": [
            "The class was activated in a sandbox. The function module itself was not verified yet. Check in SE37 that PRGN_RFC_CREATE_DERIVATION is released and RFC-enabled.",
            "If the client records changes automatically (SCC4), a transport request may be needed. An empty IV_REQUEST reaches the standard module unchanged and, if SAP needs one, the child is rejected and reported as E.",
            "The RFC user needs S_USER_AGR ACTVT 02 on the parent and all derived roles, and the authorization for profile generation (S_USER_PRO).",
        ],
    },
    "ZFM_AUTH_REQ_LIST": {
        "kind": "function_module",
        "title": "List the authorizations a function module needs",
        "summary": "Scans the source of a function module and everything it calls, and returns every authorization object and value it checks. The health check uses it to compare the whole list with the RFC user in one go.",
        "flow": [
            {"title": "Receive the function module name", "text": "IV_FUNCNAME names the module to scan. IV_MODE is S (static scan). Trace modes T and B are not implemented. IV_MAX_DEPTH limits how far it follows calls (default 3)."},
            {"title": "Add the S_RFC rows", "text": "Always returns the rows for the RFC call itself: RFC_TYPE = FUNC, RFC_NAME = the module or its group, ACTVT = 16."},
            {"title": "Read the function include", "text": "TFDIR gives the include L<group>U<nn>. SCAN ABAP-SOURCE ... WITH ANALYSIS splits it into statements."},
            {"title": "Extract every AUTHORITY-CHECK", "text": "Object, each ID and its value. A literal stays as is. A constant is replaced by its value. A variable is shown as <NAME>. DUMMY is shown as (DUMMY - not checked)."},
            {"title": "Follow the calls", "text": "INCLUDE statements, CALL FUNCTION with a literal Z or Y name, PERFORM of forms in the same group, custom global classes and local LCL_ classes of the group. The whole class is scanned, so a method that is never reached can add a row."},
            {"title": "List what it could not follow", "text": "Dynamic calls, destinations, standard callees, unreadable source and the depth limit go into the unresolved list. The result is never shorter than what the module really checks without saying so."},
            {"title": "Return JSON", "text": "EV_JSON holds the rows and the unresolved list. Sage reads it to build the authorization table."},
        ],
        "interface": {
            "importing": [_p("IV_FUNCNAME", "RS38L_FNAM"), _p("IV_MODE", "CHAR1", False, "Default 'S'."), _p("IV_MAX_DEPTH", "I", False, "Default 3."),
                          _p("IV_INCL_STANDARD", "CHAR1", True), _p("IV_TRACE_USER", "SYUNAME", True)],
            "exporting": [_p("EV_JSON", "STRING"), _p("ET_RETURN", "BAPIRET2_T")],
            "exceptions": [],
        },
        "create": [
            {"title": f"Create the function group {GROUP} if it does not exist", "text": "See the function group guide."},
            {"title": "Create the include for the local class", "text": f"Create include LZFG_MCPARCHPHSYC and add INCLUDE LZFG_MCPARCHPHSYC. to the main program of {GROUP}, next to the other class includes. It does not depend on them."},
            {"title": "Paste the local class and activate", "text": "Paste the Local class part into LZFG_MCPARCHPHSYC, then activate. Expect to fix small syntax or typing issues on the first activation."},
            {"title": "Create the function module ZFM_AUTH_REQ_LIST", "text": f"SE37, function group {GROUP}. {_REMOTE}"},
            {"title": "Define the interface", "text": f"Use the Interface tab. {_BY_VALUE}"},
            {"title": "Paste the body and activate", "text": "Then test it on ZFM_CHECK_JOB_STATUS: expect the three S_RFC rows only."},
        ],
        "parts": [
            {"label": "Local class", "file": "ZFM_AUTH_REQ_LIST.class.abap", "where": "Include LZFG_MCPARCHPHSYC"},
            {"label": "Function module body", "file": "ZFM_AUTH_REQ_LIST.body.abap", "where": "SE37 > Source code tab, below the FUNCTION line"},
        ],
        "notes": [
            "Not activated on a system yet. Check on the first activation: READ REPORT needs a flat character table (the code uses ABAPTXT255_TAB); /UI2/CL_JSON must exist (SAP_UI), otherwise build the JSON by hand; the class pool name is the class name padded with '=' to 30 characters plus CP; the function include name L<group>U<nn> from TFDIR; D010INC must list the group's includes (activate the group once if it is empty).",
            "Optional for a workflow: when this module is missing, the health check shows a warning and compares only the declared authorizations.",
        ],
    },
}


def _load(file: str) -> str:
    return (_DIR / file).read_text(encoding="utf-8")


def _used_by(workflows, oid) -> list[str]:
    return sorted(n for n, wf in workflows.items() if any(o == oid for o, _ in wf.abap_objects()))


def catalog_list(workflows, names: dict[str, str] | None = None) -> list[dict]:
    names = names or {}
    order = {"function_group": 0, "function_module": 1}
    ids = sorted(CATALOG, key=lambda i: (order[CATALOG[i]["kind"]], i))
    return [{"object_id": i, "name": names.get(i, i), "kind": CATALOG[i]["kind"], "title": CATALOG[i]["title"],
             "used_by": _used_by(workflows, i)} for i in ids]


def object_doc(oid: str, workflows, names: dict[str, str] | None = None) -> dict | None:
    doc = CATALOG.get(oid)
    if doc is None:
        return None
    names = {k: v for k, v in (names or {}).items() if k != v}
    ids = sorted(names, key=len, reverse=True)

    def sub(t):
        for i in ids:
            t = t.replace(i, names[i])
        return t

    def walk(v):
        if isinstance(v, str):
            return sub(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    out = walk({k: v for k, v in doc.items() if k != "parts"})
    out["parts"] = [{"label": p["label"], "where": sub(p["where"]), "code": sub(_load(p["file"]))} for p in doc["parts"]]
    out.update(object_id=oid, name=names.get(oid, oid), used_by=_used_by(workflows, oid))
    return out
