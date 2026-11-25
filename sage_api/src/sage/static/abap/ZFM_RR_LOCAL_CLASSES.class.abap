CLASS lcx_rr_error DEFINITION
  INHERITING FROM cx_static_check.

  PUBLIC SECTION.
    DATA reason TYPE bapi_msg READ-ONLY.

    METHODS constructor
      IMPORTING textid   LIKE textid OPTIONAL
                previous LIKE previous OPTIONAL
                reason   TYPE bapi_msg OPTIONAL.

    METHODS if_message~get_text REDEFINITION.
ENDCLASS.


CLASS lcx_rr_error IMPLEMENTATION.

  METHOD constructor.
    super->constructor( textid   = textid
                        previous = previous ).
    me->reason = reason.
  ENDMETHOD.


  METHOD if_message~get_text.
    result = COND #( WHEN reason IS NOT INITIAL
                     THEN reason
                     ELSE super->if_message~get_text( ) ).
  ENDMETHOD.

ENDCLASS.

* --- derived-role regeneration (PRGN_RFC_CREATE_DERIVATION per derived role)
CLASS lcl_rr_derived_regen DEFINITION
  FINAL.

  PUBLIC SECTION.
    TYPES child_roles TYPE STANDARD TABLE OF agr_name WITH EMPTY KEY.

    TYPES:
      BEGIN OF regeneration_result,
        return_type TYPE bapi_mtype,
        message     TYPE bapi_msg,
        transport   TYPE trkorr,
        child_count TYPE int4,
        messages    TYPE bapiret2_t,
      END OF regeneration_result.

    "! Adjusts every derived role from its parent and generates its profile.
    "! Requires S_USER_AGR change authorization (02) for the parent and every derived role.
    "! A failing child does not stop the others; each child is committed on its own.
    "! @parameter parent_role | Parent role whose derived roles are processed
    "! @parameter transport_request | Transport to use; may be initial, the first one SAP returns is reused
    "! @parameter result | S = all children done, W = no children, E = invalid/unauthorized or a child failed
    METHODS regenerate
      IMPORTING parent_role       TYPE agr_name
                transport_request TYPE trkorr
      RETURNING VALUE(result)     TYPE regeneration_result.

    "! Lists the derived roles REGENERATE would process, without changing anything.
    "! Checks the same authorizations as REGENERATE, so a successful test run proves the real run is allowed.
    "! @parameter parent_role | Parent role to inspect
    "! @parameter result | S with the child list, W = no children, E = invalid or unauthorized
    METHODS simulate
      IMPORTING parent_role   TYPE agr_name
      RETURNING VALUE(result) TYPE regeneration_result.

  PRIVATE SECTION.
    TYPES activity_code TYPE c LENGTH 2.

    CONSTANTS:
      BEGIN OF message_type,
        success TYPE bapi_mtype VALUE 'S',
        warning TYPE bapi_mtype VALUE 'W',
        error   TYPE bapi_mtype VALUE 'E',
        abort   TYPE bapi_mtype VALUE 'A',
        exit    TYPE bapi_mtype VALUE 'X',
      END OF message_type.

    CONSTANTS role_change_activity TYPE activity_code VALUE '02'.

    " PRGN_RFC_CREATE_DERIVATION reports each step as 'Y' (done) or 'N' (not done)
    CONSTANTS step_done TYPE char01 VALUE 'Y'.
    CONSTANTS option_on TYPE char01 VALUE 'X'.

    TYPES:
      BEGIN OF child_outcome,
        is_done   TYPE abap_bool,
        transport TYPE trkorr,
        messages  TYPE bapiret2_t,
      END OF child_outcome.

    METHODS check_preconditions
      IMPORTING parent_role   TYPE agr_name
                children      TYPE child_roles
      RETURNING VALUE(result) TYPE regeneration_result.

    METHODS is_authorized
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS find_unauthorized_roles
      IMPORTING roles         TYPE child_roles
      RETURNING VALUE(result) TYPE child_roles.

    METHODS role_exists
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS read_children
      IMPORTING parent_role   TYPE agr_name
      RETURNING VALUE(result) TYPE child_roles.

    METHODS adjust_child
      IMPORTING child_role        TYPE agr_name
                parent_role       TYPE agr_name
                transport_request TYPE trkorr
      RETURNING VALUE(result)     TYPE child_outcome.

    METHODS has_error
      IMPORTING messages      TYPE bapiret2_t
      RETURNING VALUE(result) TYPE abap_bool.
ENDCLASS.


CLASS lcl_rr_derived_regen IMPLEMENTATION.

  METHOD regenerate.
    DATA failed_children TYPE child_roles.

    DATA(children) = read_children( parent_role ).
    result = check_preconditions( parent_role = parent_role
                                  children    = children ).
    IF result-return_type IS NOT INITIAL.
      RETURN.
    ENDIF.

    result-transport   = transport_request.
    result-child_count = lines( children ).

    LOOP AT children INTO DATA(child_role).
      DATA(outcome) = adjust_child( child_role        = child_role
                                    parent_role       = parent_role
                                    transport_request = result-transport ).
      INSERT LINES OF outcome-messages INTO TABLE result-messages.
      IF outcome-transport IS NOT INITIAL.
        result-transport = outcome-transport.
      ENDIF.
      IF outcome-is_done = abap_false.
        INSERT child_role INTO TABLE failed_children.
      ENDIF.
    ENDLOOP.

    IF failed_children IS INITIAL.
      result-return_type = message_type-success.
      result-message     = |{ result-child_count } derived role(s) of { parent_role } adjusted and generated|.
      RETURN.
    ENDIF.

    " E, not W: executor.py counts W as success, so a partial failure would be hidden
    DATA(failed_list) = concat_lines_of( table = failed_children sep = `, ` ).
    result-return_type = message_type-error.
    result-message     = |{ lines( failed_children ) } of { result-child_count } derived role(s) failed: { failed_list }|.
  ENDMETHOD.


  METHOD simulate.
    DATA(children) = read_children( parent_role ).
    result = check_preconditions( parent_role = parent_role
                                  children    = children ).
    IF result-return_type IS NOT INITIAL.
      RETURN.
    ENDIF.

    DATA(child_list) = concat_lines_of( table = children sep = `, ` ).
    result-return_type = message_type-success.
    result-child_count = lines( children ).
    result-message     = |Test run - would adjust { result-child_count } derived role(s): { child_list }|.
  ENDMETHOD.


  METHOD check_preconditions.
    IF parent_role IS INITIAL.
      result-return_type = message_type-error.
      result-message     = `IV_ROLE_NAME is required`.
      RETURN.
    ENDIF.

    " Authorization before existence, so unauthorized callers learn nothing about the role
    IF NOT is_authorized( parent_role ).
      result-return_type = message_type-error.
      result-message     = |No S_USER_AGR change authorization (02) for role { parent_role }|.
      RETURN.
    ENDIF.

    IF NOT role_exists( parent_role ).
      result-return_type = message_type-error.
      result-message     = |Role { parent_role } does not exist|.
      RETURN.
    ENDIF.

    IF children IS INITIAL.
      result-return_type = message_type-warning.
      result-message     = |Role { parent_role } has no derived roles - nothing to regenerate|.
      RETURN.
    ENDIF.

    " Checked up front so no child is changed when the caller may not maintain all of them
    DATA(unauthorized_children) = find_unauthorized_roles( children ).
    IF unauthorized_children IS NOT INITIAL.
      DATA(unauthorized_list) = concat_lines_of( table = unauthorized_children sep = `, ` ).
      result-return_type = message_type-error.
      result-message     = |No S_USER_AGR change authorization (02) for derived role(s): { unauthorized_list }|.
    ENDIF.
  ENDMETHOD.


  METHOD is_authorized.
    AUTHORITY-CHECK OBJECT 'S_USER_AGR'
      ID 'ACT_GROUP' FIELD role
      ID 'ACTVT'     FIELD role_change_activity.
    result = xsdbool( sy-subrc = 0 ).
  ENDMETHOD.


  METHOD find_unauthorized_roles.
    LOOP AT roles INTO DATA(role).
      IF NOT is_authorized( role ).
        INSERT role INTO TABLE result.
      ENDIF.
    ENDLOOP.
  ENDMETHOD.


  METHOD role_exists.
    SELECT SINGLE @abap_true
      FROM agr_define
      WHERE agr_name = @role
      INTO @result.
  ENDMETHOD.


  METHOD read_children.
    " PARENT_AGR is not a key field; acceptable because AGR_DEFINE is small and this runs once per call
    SELECT agr_name
      FROM agr_define
      WHERE parent_agr = @parent_role
      ORDER BY agr_name
      INTO TABLE @result.
  ENDMETHOD.


  METHOD adjust_child.
    DATA derivation_done TYPE char01.
    DATA adjustment_done TYPE char01.
    DATA generation_done TYPE char01.
    DATA messages TYPE bapiret2_t.

    " PRGN function groups buffer role data per session, and one RFC session processes many roles
    CALL FUNCTION 'PRGN_CLEAR_BUFFER'.

    CALL FUNCTION 'PRGN_RFC_CREATE_DERIVATION'
      EXPORTING
        role            = child_role
        parent_role     = parent_role
        adjust_auths    = option_on
        profile_gen     = option_on
        no_dialog       = option_on
        request         = transport_request
      IMPORTING
        new_request     = result-transport
        derivation_ok   = derivation_done
        adjust_auths_ok = adjustment_done
        profile_gen_ok  = generation_done
      TABLES
        return          = messages.

    result-messages = messages.
    result-is_done  = xsdbool( derivation_done = step_done
                               AND adjustment_done = step_done
                               AND generation_done = step_done
                               AND NOT has_error( messages ) ).

    IF result-is_done = abap_true.
      COMMIT WORK AND WAIT.
      RETURN.
    ENDIF.

    ROLLBACK WORK.
    DATA(step_status) = |derive={ derivation_done } adjust={ adjustment_done } generate={ generation_done }|.
    INSERT VALUE #( type    = message_type-error
                    message = |{ child_role }: { step_status }| )
           INTO TABLE result-messages.
  ENDMETHOD.


  METHOD has_error.
    result = xsdbool( line_exists( messages[ type = message_type-error ] )
                   OR line_exists( messages[ type = message_type-abort ] )
                   OR line_exists( messages[ type = message_type-exit ] ) ).
  ENDMETHOD.

ENDCLASS.

* --- tcode removal (menu + 9 tcode objects + profile)
CLASS lcl_rr_tcode_removal DEFINITION
  FINAL.

  PUBLIC SECTION.
    TYPES:
      BEGIN OF removal_request,
        role      TYPE agr_name,
        tcode     TYPE sytcode,
        transport TYPE trkorr,
      END OF removal_request.

    TYPES:
      BEGIN OF removal_result,
        return_type    TYPE bapi_mtype,
        message        TYPE bapi_msg,
        transport      TYPE trkorr,
        removed_values TYPE int4,
        messages       TYPE bapiret2_t,
      END OF removal_result.

    METHODS constructor.

    "! Removes a transaction from the role menu and from the tcode authorization objects,
    "! then regenerates the profile. Stops at the first failing step.
    "! @parameter request | Role, transaction and optional transport request
    "! @parameter result | S = removed, W = not found or still granted by a pattern/range, E = failed
    METHODS remove
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE removal_result.

    "! Reports what REMOVE would change, without changing anything.
    "! @parameter request | Role and transaction; the transport is ignored
    "! @parameter result | Same return types as REMOVE
    METHODS simulate
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE removal_result.

  PRIVATE SECTION.
    TYPES field_values TYPE STANDARD TABLE OF pt1251 WITH EMPTY KEY.
    TYPES auth_headers TYPE STANDARD TABLE OF pt1250 WITH EMPTY KEY.
    TYPES object_range TYPE RANGE OF xuobject.

    TYPES:
      BEGIN OF removal_findings,
        was_in_menu   TYPE abap_bool,
        exact_matches TYPE field_values,
        covering_rows TYPE field_values,
      END OF removal_findings.

    TYPES:
      BEGIN OF menu_outcome,
        was_in_menu TYPE abap_bool,
        transport   TYPE trkorr,
        messages    TYPE bapiret2_t,
      END OF menu_outcome.

    TYPES:
      BEGIN OF outcome,
        return_type TYPE bapi_mtype,
        message     TYPE bapi_msg,
      END OF outcome.

    CONSTANTS:
      BEGIN OF message_type,
        success TYPE bapi_mtype VALUE 'S',
        warning TYPE bapi_mtype VALUE 'W',
        error   TYPE bapi_mtype VALUE 'E',
        abort   TYPE bapi_mtype VALUE 'A',
      END OF message_type.

    CONSTANTS option_on TYPE char01 VALUE 'X'.
    CONSTANTS activity_change TYPE c LENGTH 2 VALUE '02'.
    CONSTANTS menu_type_transaction TYPE reporttype VALUE 'TR'.
    " 'G' shows as "Maintained" in PFCG (observed on TS3 by ZFM_RR_ROLE_AUTH_CHANGE)
    CONSTANTS status_maintained TYPE tpr_st_mod VALUE 'G'.

    " PRGN_RFC_DELETE_TRANSACTION reports "transaction not in role menu" as warning S# 153
    CONSTANTS:
      BEGIN OF not_in_menu,
        id     TYPE symsgid VALUE 'S#',
        number TYPE symsgno VALUE '153',
      END OF not_in_menu.

    DATA tcode_objects TYPE object_range.

    METHODS check_preconditions
      IMPORTING request TYPE removal_request
      RAISING   lcx_rr_error.

    METHODS role_exists
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS is_composite
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS read_parent
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE par_agr.

    METHODS is_in_menu
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS remove_from_menu
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE menu_outcome
      RAISING   lcx_rr_error.

    METHODS lock
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE trkorr
      RAISING   lcx_rr_error.

    METHODS unlock
      IMPORTING role TYPE agr_name.

    METHODS read_field_values
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE field_values
      RAISING   lcx_rr_error.

    METHODS read_auth_headers
      IMPORTING role          TYPE agr_name
      RETURNING VALUE(result) TYPE auth_headers
      RAISING   lcx_rr_error.

    METHODS analyze
      IMPORTING values        TYPE field_values
                tcode         TYPE sytcode
      RETURNING VALUE(result) TYPE removal_findings.

    METHODS covers
      IMPORTING value         TYPE pt1251
                tcode         TYPE sytcode
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS remove_values
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE removal_findings
      RAISING   lcx_rr_error.

    METHODS flag_authorizations
      IMPORTING removed   TYPE field_values
                remaining TYPE field_values
      CHANGING  headers   TYPE auth_headers.

    METHODS save_values
      IMPORTING role    TYPE agr_name
                values  TYPE field_values
                headers TYPE auth_headers.

    METHODS generate_profile
      IMPORTING request       TYPE removal_request
      RETURNING VALUE(result) TYPE trkorr
      RAISING   lcx_rr_error.

    METHODS describe_outcome
      IMPORTING request       TYPE removal_request
                findings      TYPE removal_findings
                action_text   TYPE string
      RETURNING VALUE(result) TYPE outcome.

    METHODS describe_rows
      IMPORTING rows          TYPE field_values
      RETURNING VALUE(result) TYPE string.

    METHODS has_error
      IMPORTING messages      TYPE bapiret2_t
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS error_text
      IMPORTING step          TYPE string
                messages      TYPE bapiret2_t OPTIONAL
      RETURNING VALUE(result) TYPE bapi_msg.

    METHODS system_message
      RETURNING VALUE(result) TYPE string.
ENDCLASS.


CLASS lcl_rr_tcode_removal IMPLEMENTATION.

  METHOD constructor.
    " Same list as TCODE_AUTH_OBJECTS in models.py; objects missing on a system simply never match
    tcode_objects = VALUE #( sign   = 'I'
                             option = 'EQ'
                             ( low = 'S_TCODE' )
                             ( low = 'B_EM_TCODE' )
                             ( low = 'D_SD_TCODE' )
                             ( low = 'I_TCODE' )
                             ( low = 'J_3G_TCODE' )
                             ( low = 'L_TCODE' )
                             ( low = 'Q_TCODE' )
                             ( low = 'V_TCODE' )
                             ( low = 'V_SO_TCODE' ) ).
  ENDMETHOD.


  METHOD remove.
    DATA menu TYPE menu_outcome.
    DATA findings TYPE removal_findings.

    result-transport = request-transport.
    TRY.
        check_preconditions( request ).
        menu = remove_from_menu( request ).
        result-messages  = menu-messages.
        result-transport = COND #( WHEN menu-transport IS NOT INITIAL THEN menu-transport ELSE result-transport ).

        DATA(values_request) = VALUE removal_request( BASE request transport = result-transport ).
        values_request-transport = lock( values_request ).
        TRY.
            findings = remove_values( values_request ).
            IF findings-exact_matches IS NOT INITIAL.
              values_request-transport = generate_profile( values_request ).
            ENDIF.
          CLEANUP.
            unlock( request-role ).
        ENDTRY.
        unlock( request-role ).

        findings-was_in_menu  = menu-was_in_menu.
        result-transport      = values_request-transport.
        result-removed_values = lines( findings-exact_matches ).
        DATA(summary) = describe_outcome( request     = request
                                          findings    = findings
                                          action_text = `removed` ).
        result-return_type = summary-return_type.
        result-message     = summary-message.
      CATCH lcx_rr_error INTO DATA(error).
        result-return_type = message_type-error.
        result-message     = error->get_text( ).
    ENDTRY.
  ENDMETHOD.


  METHOD simulate.
    TRY.
        check_preconditions( request ).
        CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
        DATA(findings) = analyze( values = read_field_values( request-role )
                                  tcode  = request-tcode ).
        CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
        findings-was_in_menu = is_in_menu( request ).

        result-removed_values = lines( findings-exact_matches ).
        DATA(summary) = describe_outcome( request     = request
                                          findings    = findings
                                          action_text = `would be removed` ).
        result-return_type = summary-return_type.
        result-message     = |Test run, nothing changed - { summary-message }|.
      CATCH lcx_rr_error INTO DATA(error).
        result-return_type = message_type-error.
        result-message     = error->get_text( ).
    ENDTRY.
  ENDMETHOD.


  METHOD check_preconditions.
    IF request-role IS INITIAL OR request-tcode IS INITIAL.
      RAISE EXCEPTION NEW lcx_rr_error( reason = `IV_ROLE_NAME and IV_TCODE are required` ).
    ENDIF.
    IF request-role CP 'SAP_*'.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = |SAP standard role { request-role } cannot be changed - use a Z/Y copy| ).
    ENDIF.

    AUTHORITY-CHECK OBJECT 'S_USER_AGR'
      ID 'ACT_GROUP' FIELD request-role
      ID 'ACTVT'     FIELD activity_change.
    IF sy-subrc <> 0.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = |No S_USER_AGR change authorization for role { request-role }| ).
    ENDIF.

    IF NOT role_exists( request-role ).
      RAISE EXCEPTION NEW lcx_rr_error( reason = |Role { request-role } does not exist| ).
    ENDIF.
    IF is_composite( request-role ).
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = |Role { request-role } is a composite role - change its single roles instead| ).
    ENDIF.

    DATA(parent_role) = read_parent( request-role ).
    IF parent_role IS NOT INITIAL.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = |Role { request-role } is derived from { parent_role } - remove the tcode from the parent, | &&
                 |then run ZFM_RR_DERIVED_REGENERATE| ).
    ENDIF.
  ENDMETHOD.


  METHOD role_exists.
    SELECT SINGLE @abap_true FROM agr_define WHERE agr_name = @role INTO @result.
  ENDMETHOD.


  METHOD is_composite.
    SELECT SINGLE @abap_true FROM agr_agrs WHERE agr_name = @role INTO @result.
  ENDMETHOD.


  METHOD read_parent.
    SELECT SINGLE parent_agr FROM agr_define WHERE agr_name = @role INTO @result.
  ENDMETHOD.


  METHOD is_in_menu.
    SELECT SINGLE @abap_true
      FROM agr_tcodes
      WHERE agr_name = @request-role
        AND type     = @menu_type_transaction
        AND tcode    = @request-tcode
      INTO @result.
  ENDMETHOD.


  METHOD remove_from_menu.
    DATA messages TYPE bapiret2_t.

    CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
    CALL FUNCTION 'PRGN_RFC_DELETE_TRANSACTION'
      EXPORTING
        activity_group                = request-role
        tcode                         = request-tcode
        no_dialog                     = option_on
        request                       = request-transport
      IMPORTING
        new_request                   = result-transport
      TABLES
        return                        = messages
      EXCEPTIONS
        activity_group_enqueued       = 1
        activity_group_does_not_exist = 2
        namespace_problem             = 3
        tcodes_inherited_from_parent  = 4
        illegal_tcode                 = 5
        not_authorized                = 6
        profgen_tables_not_updated    = 7
        OTHERS                        = 8.
    DATA(return_code) = sy-subrc.
    result-messages = messages.

    IF return_code <> 0 OR has_error( messages ).
      DATA(step) = |Menu removal failed (code { return_code })|.
      " This module raises with MESSAGE ... RAISING, so sy-msg* belongs to this call
      DATA(raised_text) = COND string( WHEN return_code <> 0 THEN system_message( ) ).
      IF raised_text IS NOT INITIAL.
        step = |{ step }: { raised_text }|.
      ENDIF.
      ROLLBACK WORK.
      RAISE EXCEPTION NEW lcx_rr_error( reason = error_text( step     = step
                                                                          messages = messages ) ).
    ENDIF.

    COMMIT WORK AND WAIT.
    result-was_in_menu = xsdbool( NOT line_exists( messages[ id     = not_in_menu-id
                                                             number = not_in_menu-number ] ) ).
  ENDMETHOD.


  METHOD lock.
    DATA new_request TYPE trkorr.
    DATA enqueue_messages TYPE bapirettab.

    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_ENQUEUE'
      EXPORTING
        activity_group          = request-role
        no_dialog               = option_on
        request                 = request-transport
      IMPORTING
        new_request             = new_request
      TABLES
        return                  = enqueue_messages
      EXCEPTIONS
        foreign_lock            = 1
        system_error            = 2
        transport_check_problem = 3
        OTHERS                  = 4.
    DATA(return_code) = sy-subrc.
    IF return_code <> 0.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = error_text( step     = |Menu entry removed, but role { request-role } could not be locked | &&
                                        |for the authorization cleanup (code { return_code }) - run again|
                             messages = CORRESPONDING #( enqueue_messages ) ) ).
    ENDIF.

    result = COND #( WHEN new_request IS NOT INITIAL THEN new_request ELSE request-transport ).
  ENDMETHOD.


  METHOD unlock.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING
        activity_group = role.
    CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
  ENDMETHOD.


  METHOD read_field_values.
    CALL FUNCTION 'PRGN_1251_READ_FIELD_VALUES'
      EXPORTING
        activity_group    = role
      TABLES
        field_values      = result
      EXCEPTIONS
        no_data_available = 1
        OTHERS            = 2.
    " no_data_available only means the role has no authorization values yet
    IF sy-subrc = 2.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = error_text( |Authorization values of role { role } could not be read| ) ).
    ENDIF.
  ENDMETHOD.


  METHOD read_auth_headers.
    CALL FUNCTION 'PRGN_1250_READ_AUTH_DATA'
      EXPORTING
        activity_group    = role
        no_texts          = option_on
      TABLES
        auth_data         = result
      EXCEPTIONS
        no_data_available = 1
        OTHERS            = 2.
    IF sy-subrc = 2.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = error_text( |Authorizations of role { role } could not be read| ) ).
    ENDIF.
  ENDMETHOD.


  METHOD analyze.
    LOOP AT values INTO DATA(value) WHERE object IN tcode_objects.
      IF value-low = tcode AND value-high IS INITIAL.
        INSERT value INTO TABLE result-exact_matches.
      ELSEIF value-deleted = abap_false AND covers( value = value
                                                    tcode = tcode ).
        INSERT value INTO TABLE result-covering_rows.
      ENDIF.
    ENDLOOP.
  ENDMETHOD.


  METHOD covers.
    IF value-high IS NOT INITIAL.
      result = xsdbool( tcode BETWEEN value-low AND value-high ).
      RETURN.
    ENDIF.
    DATA(pattern) = condense( value-low ).
    result = xsdbool( pattern CA '*' AND tcode CP pattern ).
  ENDMETHOD.


  METHOD remove_values.
    CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
    DATA(headers) = read_auth_headers( request-role ).
    DATA(values)  = read_field_values( request-role ).
    result = analyze( values = values
                      tcode  = request-tcode ).
    IF result-exact_matches IS INITIAL.
      RETURN.
    ENDIF.
    IF headers IS INITIAL.
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = |Role { request-role } has field values but no authorizations - check it in PFCG| ).
    ENDIF.

    DELETE values WHERE object IN tcode_objects
                    AND low    = request-tcode
                    AND high   IS INITIAL.
    flag_authorizations( EXPORTING removed   = result-exact_matches
                                   remaining = values
                         CHANGING  headers   = headers ).
    save_values( role    = request-role
                 values  = values
                 headers = headers ).
  ENDMETHOD.


  METHOD flag_authorizations.
    LOOP AT headers REFERENCE INTO DATA(header).
      IF NOT line_exists( removed[ object  = header->object
                                   auth    = header->auth
                                   variant = header->variant ] ).
        CONTINUE.
      ENDIF.
      header->modified = status_maintained.
      " An authorization whose tcode field lost its last value is switched off, so that
      " generation cannot turn the empty field into a full authorization
      LOOP AT removed INTO DATA(removed_value) WHERE object  = header->object
                                                AND auth    = header->auth
                                                AND variant = header->variant.
        IF NOT line_exists( remaining[ object  = header->object
                                       auth    = header->auth
                                       variant = header->variant
                                       field   = removed_value-field ] ).
          header->deleted = option_on.
        ENDIF.
      ENDLOOP.
    ENDLOOP.
  ENDMETHOD.


  METHOD save_values.
    DATA field_rows TYPE field_values.
    DATA header_rows TYPE auth_headers.

    field_rows  = values.
    header_rows = headers.
    " Neither save module declares exceptions; both only fill the PRGN buffers
    CALL FUNCTION 'PRGN_1251_SAVE_FIELD_VALUES'
      EXPORTING
        activity_group = role
      TABLES
        field_values   = field_rows.

    CALL FUNCTION 'PRGN_1250_SAVE_AUTH_DATA'
      EXPORTING
        activity_group = role
      TABLES
        auth_data      = header_rows.

    " Writes the buffers to the database and commits. The commit may also release the role
    " lock if it was taken with update-task scope - confirm in SM12 during the TS3 test.
    CALL FUNCTION 'PRGN_UPDATE_DATABASE'.
  ENDMETHOD.


  METHOD generate_profile.
    DATA messages TYPE bapiret2_t.
    DATA new_request TYPE trkorr.

    CALL FUNCTION 'PRGN_AUTO_GENERATE_PROFILE_NEW'
      EXPORTING
        activity_group                = request-role
        no_dialog                     = option_on
        generate_profile              = option_on
        rebuild_auth_data             = abap_false
        fill_empty_fields_with_star   = abap_false
        request                       = request-transport
      IMPORTING
        new_request                   = new_request
      TABLES
        return                        = messages
      EXCEPTIONS
        activity_group_does_not_exist = 1
        activity_group_enqueued       = 2
        profile_name_exists           = 3
        profile_not_in_namespace      = 4
        no_auth_for_prof_creation     = 5
        no_auth_for_role_change       = 6
        no_auth_for_auth_maint        = 7
        no_auth_for_gen               = 8
        no_auths                      = 9
        open_auths                    = 10
        too_many_auths                = 11
        profgen_tables_not_updated    = 12
        error_when_generating_profile = 13
        OTHERS                        = 14.
    DATA(return_code) = sy-subrc.
    IF return_code <> 0 OR has_error( messages ).
      " The role is already saved at this point; only the profile is stale and still grants the tcode
      RAISE EXCEPTION NEW lcx_rr_error(
        reason = error_text( step     = |Tcode removed from role { request-role }, but profile generation | &&
                                        |failed (code { return_code }) - generate it in PFCG|
                             messages = messages ) ).
    ENDIF.

    COMMIT WORK AND WAIT.
    result = COND #( WHEN new_request IS NOT INITIAL THEN new_request ELSE request-transport ).
  ENDMETHOD.


  METHOD describe_outcome.
    DATA(removed_count) = lines( findings-exact_matches ).
    DATA(coverage) = COND string( WHEN findings-covering_rows IS NOT INITIAL
                                  THEN |; still granted by { describe_rows( findings-covering_rows ) }| ).

    IF findings-was_in_menu = abap_false AND removed_count = 0.
      result-return_type = message_type-warning.
      result-message     = |Tcode { request-tcode } not found in menu or tcode objects of { request-role }{ coverage }|.
      RETURN.
    ENDIF.

    DATA(menu_text) = COND string( WHEN findings-was_in_menu = abap_true THEN `yes` ELSE `no` ).
    result-return_type = COND #( WHEN coverage IS INITIAL THEN message_type-success ELSE message_type-warning ).
    result-message     = |Tcode { request-tcode } { action_text } from { request-role } | &&
                         |(menu entry: { menu_text }, authorization values: { removed_count }){ coverage }|.
  ENDMETHOD.


  METHOD describe_rows.
    result = concat_lines_of(
               sep   = `, `
               table = VALUE string_table(
                         FOR row IN rows
                         ( |{ row-object }-{ row-field } { row-low }| &&
                           COND string( WHEN row-high IS NOT INITIAL THEN | to { row-high }| ) ) ) ).
  ENDMETHOD.


  METHOD has_error.
    result = xsdbool( line_exists( messages[ type = message_type-error ] )
                   OR line_exists( messages[ type = message_type-abort ] ) ).
  ENDMETHOD.


  METHOD error_text.
    DATA(first_error) = VALUE bapiret2( messages[ type = message_type-error ] OPTIONAL ).
    IF first_error-message IS INITIAL.
      first_error = VALUE #( messages[ type = message_type-abort ] OPTIONAL ).
    ENDIF.
    result = COND #( WHEN first_error-message IS NOT INITIAL
                     THEN |{ step }: { first_error-message }|
                     ELSE step ).
  ENDMETHOD.


  METHOD system_message.
    IF sy-msgid IS INITIAL.
      RETURN.
    ENDIF.
    MESSAGE ID sy-msgid TYPE message_type-error NUMBER sy-msgno
            WITH sy-msgv1 sy-msgv2 sy-msgv3 sy-msgv4 INTO result.
  ENDMETHOD.

ENDCLASS.
