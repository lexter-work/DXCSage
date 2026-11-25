  DATA: lv_status TYPE btcstatus.

* --- local call - BP_JOB_STATUS_GET is standard SAP, reads TBTCO for
*     one job. Called from inside this wrapper the same "local call,
*     not remote" reasoning as ZFM_RC_START_ANALYSIS's JOB_OPEN/
*     JOB_SUBMIT/JOB_CLOSE sequence - only needed if BP_JOB_STATUS_GET
*     itself turns out not to be remote-enabled on your release; if
*     SE37's direct test call succeeds, skip this wrapper and call
*     BP_JOB_STATUS_GET directly instead. ---
  CALL FUNCTION 'BP_JOB_STATUS_GET'
    EXPORTING
      jobname  = jobname
      jobcount = jobcount
    IMPORTING
      status   = lv_status
    EXCEPTIONS
      OTHERS   = 1.
  IF sy-subrc <> 0.
    RAISE job_not_found.
  ENDIF.

  status = lv_status.
