DATA: ls_srtm_datax TYPE srtm_datax,
      lv_filename   TYPE string.

* --- authorization check: caller must be allowed to read Readiness
* Authorization is enforced by the RFC user's SAP roles. Do not add an
* unverified AUTHORITY-CHECK object here. If security requires an
* application-level check, have Basis/security define and approve the
* exact object and fields for this system first.

* --------------------------------------------------------------------
* CONFIRMED on TS3 (2026-09-18, debugger, real call, SY-SUBRC 0, XTEXT
* populated) - see "WHAT'S CONFIRMED vs. STILL OPEN" above. TRIGOFFSET
* is NOT 999999999 like TRIGID/SUBID - SELECT_W_CLT_CONSIDRATION rewrites
* it per-client internally, so the raw literal differs from the other
* two. Still open: whether 999991810 holds on other systems or after a
* new collection run - re-confirm via debugger (STEP 4) if this starts
* returning ARCHIVE_NOT_FOUND.
  ls_srtm_datax = cl_rc_collect_client_handler=>select_w_clt_considration(
    iv_trigid     = 999999999
    iv_trigoffset = 999991810
    iv_subid      = 222 ).

  IF ls_srtm_datax-xtext IS INITIAL.
    RAISE archive_not_found.
  ENDIF.

  lv_filename = |RC_ANALYSIS_{ sy-sysid }_{ sy-datum }.zip|.
* --------------------------------------------------------------------

  filename = lv_filename.
  zip_data = ls_srtm_datax-xtext.
