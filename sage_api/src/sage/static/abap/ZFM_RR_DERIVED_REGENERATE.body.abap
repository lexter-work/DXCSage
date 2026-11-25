DATA(regeneration) = NEW lcl_rr_derived_regen( ).
DATA(parent_role) = CONV agr_name( to_upper( condense( iv_role_name ) ) ).

" An empty IV_REQUEST reaches PRGN_RFC_CREATE_DERIVATION unchanged; if SAP needs one, it rejects
" the child in RETURN and the class reports E - never a silent success
DATA(result) = COND lcl_rr_derived_regen=>regeneration_result(
                 WHEN iv_test_run = abap_true
                 THEN regeneration->simulate( parent_role )
                 ELSE regeneration->regenerate( parent_role       = parent_role
                                                transport_request = iv_request ) ).

ev_return_type = result-return_type.
ev_return_msg  = result-message.
ev_transport   = result-transport.
et_return      = result-messages.
