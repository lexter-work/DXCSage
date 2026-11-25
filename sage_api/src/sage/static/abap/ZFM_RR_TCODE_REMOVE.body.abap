DATA(request) = VALUE lcl_rr_tcode_removal=>removal_request(
                  role      = to_upper( condense( iv_role_name ) )
                  tcode     = to_upper( condense( iv_tcode ) )
                  transport = iv_request ).
DATA(removal) = NEW lcl_rr_tcode_removal( ).

DATA(result) = COND lcl_rr_tcode_removal=>removal_result(
                 WHEN iv_test_run = abap_true
                 THEN removal->simulate( request )
                 ELSE removal->remove( request ) ).

ev_return_type    = result-return_type.
ev_return_msg     = result-message.
ev_transport      = result-transport.
ev_removed_count  = result-removed_values.
et_return         = result-messages.
