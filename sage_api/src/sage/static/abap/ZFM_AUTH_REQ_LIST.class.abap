CLASS lcl_auth_req_list DEFINITION
  FINAL.

  PUBLIC SECTION.
    TYPES: BEGIN OF row,
             auth_object TYPE string,
             auth_field  TYPE string,
             auth_values TYPE string,
             source      TYPE string,
             depth       TYPE i,
             callee_path TYPE string,
           END OF row,
           rows    TYPE STANDARD TABLE OF row WITH DEFAULT KEY,
           strings TYPE STANDARD TABLE OF string WITH DEFAULT KEY,
           BEGIN OF result_type,
             json   TYPE string,
             return TYPE bapiret2_t,
           END OF result_type.

    METHODS analyze
      IMPORTING funcname      TYPE rs38l_fnam
                mode          TYPE char1
                max_depth     TYPE i
                incl_standard TYPE char1
                trace_user    TYPE syuname
      RETURNING VALUE(result) TYPE result_type.

  PRIVATE SECTION.
    TYPES: tokens_type     TYPE STANDARD TABLE OF stokesx WITH DEFAULT KEY,
           statements_type TYPE STANDARD TABLE OF sstmnt WITH DEFAULT KEY,
           BEGIN OF context,
             include TYPE string,
             group   TYPE string,
             depth   TYPE i,
             path    TYPE string,
           END OF context,
           BEGIN OF constant_entry,
             const_name  TYPE string,
             const_value TYPE string,
           END OF constant_entry,
           BEGIN OF output,
             rows       TYPE rows,
             unresolved TYPE strings,
           END OF output.

    DATA: known_constants TYPE STANDARD TABLE OF constant_entry WITH DEFAULT KEY,
          found_rows     TYPE rows,
          unresolved     TYPE strings,
          seen           TYPE strings,
          depth_limit    TYPE i,
          follow_standard TYPE abap_bool.

    METHODS is_allowed
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS add_rfc_rows
      IMPORTING funcname TYPE rs38l_fnam.

    METHODS scan_function
      IMPORTING funcname TYPE rs38l_fnam
                ctx      TYPE context.

    METHODS scan_include
      IMPORTING include_name TYPE string
                ctx          TYPE context.

    METHODS load
      IMPORTING include_name TYPE string
      EXPORTING tokens     TYPE tokens_type
                statements TYPE statements_type
                ok         TYPE abap_bool.

    METHODS handle_statement
      IMPORTING tokens    TYPE tokens_type
                statement TYPE sstmnt
                ctx       TYPE context.

    METHODS add_authority_check
      IMPORTING words TYPE strings
                line  TYPE i
                ctx   TYPE context.

    METHODS follow_call_function
      IMPORTING words TYPE strings
                ctx   TYPE context.

    METHODS follow_perform
      IMPORTING words TYPE strings
                ctx   TYPE context.

    METHODS follow_form
      IMPORTING form TYPE string
                ctx  TYPE context.

    METHODS follow_block
      IMPORTING kind     TYPE string
                name     TYPE string
                end_kind TYPE string
                ctx      TYPE context.

    METHODS collect_constants
      IMPORTING tokens     TYPE tokens_type
                statements TYPE statements_type.

    METHODS resolve_constants.

    METHODS resolve
      IMPORTING text          TYPE string
      RETURNING VALUE(result) TYPE string.

    METHODS follow_class_refs
      IMPORTING words TYPE strings
                ctx   TYPE context.

    METHODS follow_class
      IMPORTING class_name TYPE string
                ctx   TYPE context.

    METHODS add_row
      IMPORTING auth_object TYPE string
                auth_field  TYPE string
                auth_values TYPE string
                source      TYPE string
                ctx         TYPE context.

    METHODS note
      IMPORTING text TYPE string.

    METHODS is_literal
      IMPORTING word          TYPE string
      RETURNING VALUE(result) TYPE abap_bool.

    METHODS value_of
      IMPORTING word          TYPE string
      RETURNING VALUE(result) TYPE string.
ENDCLASS.


CLASS lcl_auth_req_list IMPLEMENTATION.

  METHOD analyze.
    IF mode NA 'STB' OR max_depth < 0 OR max_depth > 10.
      result-return = VALUE #( ( type = 'E' message = 'IV_MODE must be S, T or B and IV_MAX_DEPTH 0..10' ) ).
      RETURN.
    ENDIF.
    IF is_allowed( ) = abap_false.
      result-return = VALUE #( ( type = 'E' message = 'No authorization to read function group source (S_DEVELOP display)' ) ).
      RETURN.
    ENDIF.

    DATA(fm) = CONV rs38l_fnam( to_upper( funcname ) ).
    SELECT SINGLE funcname FROM tfdir WHERE funcname = @fm INTO @DATA(found).
    IF sy-subrc <> 0.
      result-return = VALUE #( ( type = 'E' message = |Function module { fm } not found| ) ).
      RETURN.
    ENDIF.

    depth_limit     = max_depth.
    follow_standard = xsdbool( incl_standard = 'X' ).

    IF mode CA 'SB'.
      add_rfc_rows( fm ).
      scan_function( funcname = fm ctx = VALUE #( path = fm ) ).
    ENDIF.
    IF mode CA 'TB'.
      INSERT VALUE #( type = 'W'
                      message = |Trace mode is not implemented (trace user { trace_user }); static result only| )
        INTO TABLE result-return.
    ENDIF.

    resolve_constants( ).
    DATA(out) = VALUE output( rows = found_rows unresolved = unresolved ).
    result-json = /ui2/cl_json=>serialize(
      data        = out
      pretty_name = /ui2/cl_json=>pretty_mode-low_case ).
  ENDMETHOD.


  METHOD is_allowed.
    AUTHORITY-CHECK OBJECT 'S_DEVELOP'
      ID 'DEVCLASS' DUMMY
      ID 'OBJTYPE'  FIELD 'FUGR'
      ID 'OBJNAME'  DUMMY
      ID 'P_GROUP'  DUMMY
      ID 'ACTVT'    FIELD '03'.
    result = xsdbool( sy-subrc = 0 ).
  ENDMETHOD.


  METHOD add_rfc_rows.
    SELECT SINGLE pname FROM tfdir WHERE funcname = @funcname INTO @DATA(pname).
    DATA(group) = CONV string( pname ).
    REPLACE FIRST OCCURRENCE OF 'SAPL' IN group WITH ''.
    DATA(ctx) = VALUE context( path = funcname ).
    add_row( auth_object = 'S_RFC' auth_field = 'RFC_TYPE' auth_values = 'FUNC' source = 'RFC_CALL' ctx = ctx ).
    add_row( auth_object = 'S_RFC' auth_field = 'RFC_NAME'
             auth_values = |{ funcname } or function group { group }| source = 'RFC_CALL' ctx = ctx ).
    add_row( auth_object = 'S_RFC' auth_field = 'ACTVT' auth_values = '16' source = 'RFC_CALL' ctx = ctx ).
  ENDMETHOD.


  METHOD scan_function.
    IF ctx-depth > depth_limit.
      note( |{ funcname } (depth limit { depth_limit } reached)| ).
      RETURN.
    ENDIF.
    IF line_exists( seen[ table_line = |FM:{ funcname }| ] ).
      RETURN.
    ENDIF.
    APPEND |FM:{ funcname }| TO seen.

    SELECT SINGLE pname, include FROM tfdir WHERE funcname = @funcname INTO @DATA(tf).
    IF sy-subrc <> 0.
      note( |{ funcname } (function module not found)| ).
      RETURN.
    ENDIF.

    DATA(program) = CONV string( tf-pname ).
    DATA(function_include) = program.
    REPLACE FIRST OCCURRENCE OF 'SAPL' IN function_include WITH 'L'.
    function_include = |{ function_include }U{ tf-include }|.

    scan_include( include_name = function_include
                  ctx     = VALUE #( include = function_include
                                     group   = program
                                     depth   = ctx-depth
                                     path    = ctx-path ) ).
  ENDMETHOD.


  METHOD scan_include.
    DATA(name) = to_upper( include_name ).
    IF line_exists( seen[ table_line = |INC:{ name }| ] ).
      RETURN.
    ENDIF.
    APPEND |INC:{ name }| TO seen.

    load( EXPORTING include_name = name
          IMPORTING tokens     = DATA(tokens)
                    statements = DATA(statements)
                    ok         = DATA(ok) ).
    IF ok = abap_false.
      note( |{ name } (source not readable)| ).
      RETURN.
    ENDIF.

    DATA(here) = ctx.
    here-include = name.
    LOOP AT statements INTO DATA(statement).
      handle_statement( tokens = tokens statement = statement ctx = here ).
    ENDLOOP.
  ENDMETHOD.


  METHOD load.
    DATA source TYPE abaptxt255_tab.
    DATA program TYPE progname.

    program = include_name.
    READ REPORT program INTO source.
    IF sy-subrc <> 0.
      ok = abap_false.
      RETURN.
    ENDIF.
    SCAN ABAP-SOURCE source TOKENS INTO tokens STATEMENTS INTO statements WITH ANALYSIS.
    ok = xsdbool( tokens IS NOT INITIAL ).
    IF ok = abap_true.
      collect_constants( tokens = tokens statements = statements ).
    ENDIF.
  ENDMETHOD.


  METHOD handle_statement.
    IF statement-from > statement-to.
      RETURN.
    ENDIF.

    DATA words TYPE strings.
    LOOP AT tokens INTO DATA(token) FROM statement-from TO statement-to.
      APPEND token-str TO words.
    ENDLOOP.

    DATA(line) = tokens[ statement-from ]-row.
    CASE to_upper( words[ 1 ] ).
      WHEN 'AUTHORITY-CHECK'.
        add_authority_check( words = words line = line ctx = ctx ).
      WHEN 'INCLUDE'.
        IF lines( words ) = 2 OR ( lines( words ) = 4 AND to_upper( words[ 3 ] ) = 'IF' ).
          scan_include( include_name = words[ 2 ] ctx = ctx ).
        ENDIF.
      WHEN 'CALL'.
        IF lines( words ) >= 3 AND to_upper( words[ 2 ] ) = 'FUNCTION'.
          follow_call_function( words = words ctx = ctx ).
        ENDIF.
      WHEN 'PERFORM'.
        follow_perform( words = words ctx = ctx ).
    ENDCASE.

    follow_class_refs( words = words ctx = ctx ).
  ENDMETHOD.


  METHOD add_authority_check.
    IF lines( words ) < 3 OR to_upper( words[ 2 ] ) <> 'OBJECT'.
      note( |AUTHORITY-CHECK without literal OBJECT clause ({ ctx-include }:{ line })| ).
      RETURN.
    ENDIF.

    DATA(object) = value_of( words[ 3 ] ).
    DATA(source) = |STATIC:{ ctx-include }:{ line }|.
    DATA(i) = 4.
    WHILE i <= lines( words ).
      IF to_upper( words[ i ] ) = 'ID' AND i + 2 <= lines( words ).
        DATA(id_field) = value_of( words[ i + 1 ] ).
        DATA(kind) = to_upper( words[ i + 2 ] ).
        IF kind = 'FIELD' AND i + 3 <= lines( words ).
          add_row( auth_object = object auth_field = id_field
                   auth_values = value_of( words[ i + 3 ] ) source = source ctx = ctx ).
          i = i + 4.
        ELSEIF kind = 'DUMMY'.
          add_row( auth_object = object auth_field = id_field
                   auth_values = '(DUMMY - not checked)' source = source ctx = ctx ).
          i = i + 3.
        ELSE.
          i = i + 1.
        ENDIF.
      ELSE.
        i = i + 1.
      ENDIF.
    ENDWHILE.
  ENDMETHOD.


  METHOD follow_call_function.
    IF is_literal( words[ 3 ] ) = abap_false.
      note( |CALL FUNCTION { words[ 3 ] } (dynamic name, in { ctx-include })| ).
      RETURN.
    ENDIF.

    DATA(callee) = CONV rs38l_fnam( to_upper( value_of( words[ 3 ] ) ) ).
    LOOP AT words TRANSPORTING NO FIELDS WHERE table_line CP 'DESTINATION'.
      note( |{ callee } (remote call via DESTINATION, in { ctx-include })| ).
      RETURN.
    ENDLOOP.

    IF callee(1) NA 'ZY' AND follow_standard = abap_false.
      note( |{ callee } (SAP standard, not followed)| ).
      RETURN.
    ENDIF.

    scan_function( funcname = callee
                   ctx      = VALUE #( BASE ctx depth = ctx-depth + 1 path = |{ ctx-path }>{ callee }| ) ).
  ENDMETHOD.


  METHOD follow_perform.
    IF lines( words ) < 2.
      RETURN.
    ENDIF.
    IF words[ 2 ] CS '('.
      note( |PERFORM { words[ 2 ] } (dynamic name, in { ctx-include })| ).
      RETURN.
    ENDIF.
    LOOP AT words TRANSPORTING NO FIELDS WHERE table_line CP 'PROGRAM'.
      note( |PERFORM { words[ 2 ] } (IN PROGRAM, not followed, in { ctx-include })| ).
      RETURN.
    ENDLOOP.
    follow_form( form = to_upper( words[ 2 ] ) ctx = ctx ).
  ENDMETHOD.


  METHOD follow_form.
    follow_block( kind = 'FORM' name = form end_kind = 'ENDFORM' ctx = ctx ).
  ENDMETHOD.


  METHOD follow_block.
    " Scans one FORM ... ENDFORM or CLASS ... IMPLEMENTATION ... ENDCLASS block that
    " lives in an include of the caller's function group.
    DATA(label) = |{ kind } { name }|.
    IF ctx-group IS INITIAL.
      note( |{ label } (location unknown, in { ctx-include })| ).
      RETURN.
    ENDIF.
    IF ctx-depth + 1 > depth_limit.
      note( |{ label } (depth limit { depth_limit } reached)| ).
      RETURN.
    ENDIF.
    IF line_exists( seen[ table_line = |BLK:{ ctx-group }:{ label }| ] ).
      RETURN.
    ENDIF.
    APPEND |BLK:{ ctx-group }:{ label }| TO seen.

    SELECT include FROM d010inc WHERE master = @ctx-group INTO TABLE @DATA(includes).
    LOOP AT includes INTO DATA(inc).
      load( EXPORTING include_name = CONV string( inc-include )
            IMPORTING tokens       = DATA(tokens)
                      statements   = DATA(statements)
                      ok           = DATA(ok) ).
      IF ok = abap_false.
        CONTINUE.
      ENDIF.

      DATA(inside) = abap_false.
      LOOP AT statements INTO DATA(statement).
        IF statement-from > statement-to.
          CONTINUE.
        ENDIF.
        DATA(first) = to_upper( tokens[ statement-from ]-str ).
        IF inside = abap_false.
          IF first = kind AND statement-to > statement-from
             AND to_upper( tokens[ statement-from + 1 ]-str ) = name
             AND ( kind <> 'CLASS'
                   OR ( statement-to > statement-from + 1
                        AND to_upper( tokens[ statement-from + 2 ]-str ) = 'IMPLEMENTATION' ) ).
            inside = abap_true.
          ENDIF.
          CONTINUE.
        ENDIF.
        IF first = end_kind.
          RETURN.
        ENDIF.
        handle_statement(
          tokens    = tokens
          statement = statement
          ctx       = VALUE #( include = CONV string( inc-include )
                               group   = ctx-group
                               depth   = ctx-depth + 1
                               path    = |{ ctx-path }>{ label }| ) ).
      ENDLOOP.
      IF inside = abap_true.
        RETURN.
      ENDIF.
    ENDLOOP.
    note( |{ label } (not found in the includes of { ctx-group })| ).
  ENDMETHOD.


  METHOD follow_class_refs.
    DATA(text) = to_upper( concat_lines_of( table = words sep = ` ` ) ).
    FIND ALL OCCURRENCES OF PCRE '\b(?:[ZY]CL_|LCL_)[A-Z0-9_]+' IN text RESULTS DATA(matches).
    LOOP AT matches INTO DATA(match).
      follow_class( class_name = substring( val = text off = match-offset len = match-length ) ctx = ctx ).
    ENDLOOP.
  ENDMETHOD.


  METHOD follow_class.
    IF substring( val = class_name len = 1 ) = 'L'.
      " local class: defined in an include of the caller's function group
      follow_block( kind = 'CLASS' name = class_name end_kind = 'ENDCLASS' ctx = ctx ).
      RETURN.
    ENDIF.
    IF line_exists( seen[ table_line = |CL:{ class_name }| ] ).
      RETURN.
    ENDIF.
    SELECT SINGLE clsname FROM seoclass WHERE clsname = @class_name INTO @DATA(exists).
    IF sy-subrc <> 0.
      RETURN.
    ENDIF.
    IF ctx-depth + 1 > depth_limit.
      note( |{ class_name } (depth limit { depth_limit } reached)| ).
      RETURN.
    ENDIF.
    APPEND |CL:{ class_name }| TO seen.

    " Class pool program name: class name padded with '=' to 30 characters, then CP
    DATA(pool) = |{ class_name WIDTH = 30 PAD = '=' }CP|.
    scan_include( include_name = pool
                  ctx          = VALUE #( include = pool
                                          group   = ``
                                          depth   = ctx-depth + 1
                                          path    = |{ ctx-path }>{ class_name }| ) ).
  ENDMETHOD.


  METHOD collect_constants.
    " CONSTANTS name ... VALUE 'literal' -> remembered so AUTHORITY-CHECK FIELD name can show its value
    LOOP AT statements INTO DATA(statement).
      IF statement-from >= statement-to
         OR to_upper( tokens[ statement-from ]-str ) <> 'CONSTANTS'.
        CONTINUE.
      ENDIF.
      DATA(const_name) = to_upper( tokens[ statement-from + 1 ]-str ).
      IF const_name = 'BEGIN' OR const_name = 'END'.
        CONTINUE.
      ENDIF.
      LOOP AT tokens INTO DATA(token) FROM statement-from + 2 TO statement-to.
        IF to_upper( token-str ) = 'VALUE'.
          DATA(value_index) = sy-tabix + 1.
          IF value_index <= statement-to AND is_literal( tokens[ value_index ]-str ) = abap_true.
            DATA(entry) = VALUE constant_entry( const_name  = const_name
                                                const_value = value_of( tokens[ value_index ]-str ) ).
            IF NOT line_exists( known_constants[ const_name = entry-const_name const_value = entry-const_value ] ).
              APPEND entry TO known_constants.
            ENDIF.
          ENDIF.
          EXIT.
        ENDIF.
      ENDLOOP.
    ENDLOOP.
  ENDMETHOD.


  METHOD resolve_constants.
    LOOP AT found_rows REFERENCE INTO DATA(row).
      row->auth_object = resolve( row->auth_object ).
      row->auth_field  = resolve( row->auth_field ).
      row->auth_values = resolve( row->auth_values ).
    ENDLOOP.
  ENDMETHOD.


  METHOD resolve.
    " <NAME> -> value, only when every CONSTANTS definition of NAME agrees on one value
    result = text.
    IF strlen( text ) < 3
       OR substring( val = text len = 1 ) <> '<'
       OR substring( val = text off = strlen( text ) - 1 len = 1 ) <> '>'.
      RETURN.
    ENDIF.
    DATA(wanted) = substring( val = text off = 1 len = strlen( text ) - 2 ).
    DATA found_values TYPE strings.
    LOOP AT known_constants INTO DATA(entry) WHERE const_name = wanted.
      IF NOT line_exists( found_values[ table_line = entry-const_value ] ).
        APPEND entry-const_value TO found_values.
      ENDIF.
    ENDLOOP.
    IF lines( found_values ) = 1.
      result = found_values[ 1 ].
    ENDIF.
  ENDMETHOD.


  METHOD add_row.
    APPEND VALUE #( auth_object = auth_object
                    auth_field  = auth_field
                    auth_values = auth_values
                    source      = source
                    depth       = ctx-depth
                    callee_path = ctx-path ) TO found_rows.
  ENDMETHOD.


  METHOD note.
    IF NOT line_exists( unresolved[ table_line = text ] ).
      APPEND text TO unresolved.
    ENDIF.
  ENDMETHOD.


  METHOD is_literal.
    result = xsdbool( strlen( word ) >= 2 AND ( word(1) = `'` OR word(1) = '`' ) ).
  ENDMETHOD.


  METHOD value_of.
    IF is_literal( word ) = abap_true.
      result = to_upper( substring( val = word off = 1 len = strlen( word ) - 2 ) ).
    ELSE.
      result = |<{ to_upper( word ) }>|.
    ENDIF.
  ENDMETHOD.

ENDCLASS.
