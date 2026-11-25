DATA(result) = NEW lcl_auth_req_list( )->analyze(
  funcname      = iv_funcname
  mode          = iv_mode
  max_depth     = iv_max_depth
  incl_standard = iv_incl_standard
  trace_user    = iv_trace_user ).

ev_json   = result-json.
et_return = result-return.
