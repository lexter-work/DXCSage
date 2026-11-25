  DATA: lv_jobname  TYPE btcjob,
        lv_jobcount TYPE btcjobcnt.

  CONSTANTS: lc_program TYPE sy-repid VALUE 'PROFGEN_CORR_REPORT_2'.

  lv_jobname = jobname.

* --- authorization check: caller must be allowed to schedule
*     background jobs. Same object ZFM_RC_START_ANALYSIS uses.
  AUTHORITY-CHECK OBJECT 'S_BTCH_JOB'
    ID 'JOBACTION' FIELD 'RELE'
    ID 'JOBGROUP'  DUMMY.
  IF sy-subrc <> 0.
    RAISE no_authorization.
  ENDIF.

* --- open the job. LOCAL call - see WHY THIS EXISTS above. ---
  CALL FUNCTION 'JOB_OPEN'
    EXPORTING
      jobname              = lv_jobname
    IMPORTING
      jobcount             = lv_jobcount
    EXCEPTIONS
      cant_create_job      = 1
      invalid_job_data     = 2
      job_create_canceled  = 3
      OTHERS               = 4.
  IF sy-subrc <> 0.
    RAISE job_open_failed.
  ENDIF.

* --- submit the report as the job's one step. VARIANT blank runs the
*     report's own defaults - confirmed to mean "all roles" for
*     PROFGEN_CORR_REPORT_2 specifically (see CONFIRMED above). REPORT
*     is fixed to lc_program - there is no caller-supplied program name
*     on this wrapper's interface at all. ---
  CALL FUNCTION 'JOB_SUBMIT'
    EXPORTING
      authcknam                       = sy-uname
      jobcount                        = lv_jobcount
      jobname                         = lv_jobname
      report                          = lc_program
      variant                         = variant
    EXCEPTIONS
      bad_priparams                   = 1
      bad_xpgflags                    = 2
      invalid_jobdata                 = 3
      jobname_missing                 = 4
      job_notex                       = 5
      job_submit_active                = 6
      lock_failed                     = 7
      program_missing                 = 8
      prog_abap_and_variant_specified = 9
      OTHERS                          = 10.
  IF sy-subrc <> 0.
    RAISE job_submit_failed.
  ENDIF.

* --- release the job to start immediately. ---
  CALL FUNCTION 'JOB_CLOSE'
    EXPORTING
      jobcount              = lv_jobcount
      jobname                = lv_jobname
      strtimmed              = 'X'
    EXCEPTIONS
      cant_start_immediate  = 1
      deadline_not_allowed  = 2
      invalid_startdate     = 3
      jobname_missing       = 4
      job_close_failed      = 5
      job_nosteps           = 6
      job_notex              = 7
      lock_failed            = 8
      OTHERS                  = 9.
  IF sy-subrc <> 0.
    RAISE job_close_failed.
  ENDIF.

  real_jobname = lv_jobname.
  jobcount     = lv_jobcount.
