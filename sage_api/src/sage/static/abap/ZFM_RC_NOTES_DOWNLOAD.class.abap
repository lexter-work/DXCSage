CLASS lcl_rc_notes_download DEFINITION
  FINAL
  CREATE PRIVATE.

  PUBLIC SECTION.
    TYPES: BEGIN OF schedule_result,
             schedule_id TYPE cwbschld,
             run_id      TYPE cwbrun_id,
             job_count   TYPE btcjobcnt,
             return      TYPE bapiret2_t,
           END OF schedule_result.

    CLASS-METHODS new
      RETURNING VALUE(result) TYPE REF TO lcl_rc_notes_download.

    METHODS schedule_download
      IMPORTING notes         TYPE cwb_t_note
                description   TYPE text80
      RETURNING VALUE(result) TYPE schedule_result.

  PRIVATE SECTION.
    METHODS is_authorized
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS clean_notes
      IMPORTING notes         TYPE cwb_t_note
      RETURNING VALUE(result) TYPE cwb_t_note.

    METHODS error_message
      IMPORTING text          TYPE csequence
      RETURNING VALUE(result) TYPE bapiret2.
ENDCLASS.


CLASS lcl_rc_notes_download IMPLEMENTATION.

  METHOD new.
    result = NEW #( ).
  ENDMETHOD.


  METHOD schedule_download.
    IF is_authorized( ) = abap_false.
      INSERT error_message( `No authorization to schedule the SAP Note download job` ) INTO TABLE result-return.
      RETURN.
    ENDIF.

    DATA(clean_note_list) = clean_notes( notes ).
    IF clean_note_list IS INITIAL.
      INSERT error_message( `No SAP Note number supplied` ) INTO TABLE result-return.
      RETURN.
    ENDIF.

    DATA(bgjob_info) = VALUE scwn_dark_s_schdl_bgjob_info(
      descr        = COND #( WHEN description IS INITIAL THEN `RFC SAP Note download` ELSE description )
      schdl_option = if_scwn_dark_constants=>ac_schdl_opt_i ).

    TRY.
        cl_scwn_dark_api=>schedule_download(
          EXPORTING
            is_schedule_bgjob_info = bgjob_info
            it_notes               = clean_note_list
          IMPORTING
            es_schedule_info       = DATA(schedule_info) ).

      CATCH cx_scwn_dark INTO DATA(dark_error).
        INSERT error_message( dark_error->get_text( ) ) INTO TABLE result-return.
        RETURN.

      CATCH cx_root INTO DATA(unexpected_error).
        INSERT error_message( |Unexpected error while scheduling the download: { unexpected_error->get_text( ) }| )
          INTO TABLE result-return.
        RETURN.
    ENDTRY.

    result-schedule_id = schedule_info-schedule_id.
    result-run_id      = schedule_info-run_id.
    result-job_count   = schedule_info-job_count.

    INSERT VALUE #( type    = 'S'
                    message = |Download job scheduled, schedule { schedule_info-schedule_id }, run { schedule_info-run_id }| )
           INTO TABLE result-return.
  ENDMETHOD.


  METHOD is_authorized.
    AUTHORITY-CHECK OBJECT 'S_BTCH_JOB'
      ID 'JOBACTION' FIELD 'RELE'
      ID 'JOBGROUP'  FIELD '*'.
    result = xsdbool( sy-subrc = 0 ).
  ENDMETHOD.


  METHOD clean_notes.
    result = notes.
    SORT result.
    DELETE ADJACENT DUPLICATES FROM result.
    DELETE result WHERE table_line IS INITIAL.
  ENDMETHOD.


  METHOD error_message.
    result = VALUE #( type = 'E' message = text ).
  ENDMETHOD.

ENDCLASS.
