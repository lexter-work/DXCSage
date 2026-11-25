  DATA: lv_listident  TYPE tbtcp-listident,
        lv_rqident    TYPE tsp01-rqident.

* --- STEP A: find the spool request this job's step created.
*     TBTCP is a plain table read, no XBP needed. If this comes back
*     empty on your system, this function module's interface needs to
*     change to accept SPOOLNUM as a caller-supplied import instead. ---
  SELECT SINGLE listident FROM tbtcp
    INTO lv_listident
    WHERE jobname  = jobname
      AND jobcount = jobcount
      AND stepcount = 1.
  IF sy-subrc <> 0 OR lv_listident IS INITIAL.
    RAISE job_not_found.
  ENDIF.

  spoolnum = lv_listident.

* --- CONFIRMED bug on TS3 (2026-09-22, real dump text): RQIDENT is
*     typed TSP01-RQIDENT, domain RSPOID - a numeric 4-byte type, not
*     TBTCP-LISTIDENT's CHAR(20). Passing lv_listident straight into
*     RQIDENT raised CX_SY_DYN_CALL_ILLEGAL_TYPE / CALL_FUNCTION_
*     CONFLICT_TYPE (dump quoted "Technical type of the formal
*     parameter: I" vs. "actual parameter: TBTCP-LISTIDENT"). Explicit
*     conversion required before the call. ---
  lv_rqident = lv_listident.

* --- STEP B: read the spool content. RSPO_RETURN_ABAP_SPOOLJOB is a
*     plain function module (not XBP). CONFIRMED bug on TS3
*     (2026-09-22, real dump text): BUFFER is a MANDATORY TABLES
*     parameter on this FM (dump: CX_SY_DYN_CALL_PARAM_MISSING,
*     "the required parameter BUFFER was not filled") - not optional,
*     and separate from LISTOBJECT. BUFFER already returns the spool's
*     flattened text lines directly, so LISTOBJECT and a second
*     LIST_TO_ASCI conversion step (this file's earlier design) are
*     unnecessary - feed BUFFER straight into LISTLINES (already
*     SOLI-typed, 255 chars, matching BUFFER's expected line shape).
*     RSPO_R_RDI_GET_SPOOL_JOB_ITEM and EPS_GET_SPOOL_LIST (this file's
*     earlier suggested alternates) are CONFIRMED NOT TO EXIST on TS3 -
*     don't try them. If RSPO_RETURN_ABAP_SPOOLJOB itself doesn't pan
*     out, RSPO_R_RETURN_RAW_DATA is a real, remote-enabled candidate
*     confirmed to exist on TS3, but it takes no RQIDENT/spool-ID
*     import at all - it looks like it expects to run against a spool
*     job already selected via some other RFC/session mechanism, not a
*     standalone "read spool N" call like this wrapper needs. Treat it
*     as an unverified, bigger redesign, not a drop-in swap, if it ever
*     comes to that. ---
  CALL FUNCTION 'RSPO_RETURN_ABAP_SPOOLJOB'
    EXPORTING
      rqident              = lv_rqident
    TABLES
      buffer               = listlines
    EXCEPTIONS
      no_such_job           = 1
      not_abap_list          = 2
      job_contains_no_data  = 3
      selection_empty       = 4
      no_permission         = 5
      can_not_access        = 6
      read_error             = 7
      OTHERS                  = 8.
  IF sy-subrc <> 0.
    RAISE spool_read_failed.
  ENDIF.

  IF listlines[] IS INITIAL.
    RAISE no_spool_found.
  ENDIF.
