DATA(result) = lcl_rc_notes_download=>new( )->schedule_download(
  notes       = it_notes
  description = iv_description ).

ev_schedule_id = result-schedule_id.
ev_run_id      = result-run_id.
ev_job_count   = result-job_count.
et_return      = result-return.
