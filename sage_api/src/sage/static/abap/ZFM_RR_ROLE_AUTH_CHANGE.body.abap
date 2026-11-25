  DATA: lv_agr_name TYPE agr_name,
        lv_request  TYPE trkorr,
        ls_add      TYPE zrole_auth_value,
        ls_del      TYPE zrole_auth_value,
        lt_auth     TYPE STANDARD TABLE OF pt1250,
        lt_fields   TYPE STANDARD TABLE OF pt1251,
        ls_field    TYPE pt1251,
        ls_auth     TYPE pt1250,
        lt_return   TYPE bapirettab,
        lt_gen_ret  TYPE STANDARD TABLE OF bapiret2.
  FIELD-SYMBOLS: <fs_auth> TYPE pt1250.
* Observed in AGR_1251 on TS3: MODIFIED = 'S' shows as "Standard" in
* PFCG, 'G' shows as "Maintained" (manually maintained). Our values are
* manual, so 'G'. Still CONFIRM the domain behind TPR_ST_MOD in SE11.
  CONSTANTS: c_modified TYPE tpr_st_mod VALUE 'G'.

  lv_agr_name = activity_group.

  AUTHORITY-CHECK OBJECT 'S_USER_AGR'
    ID 'ACTVT'     FIELD '02'
    ID 'ACT_GROUP' FIELD lv_agr_name.
  IF sy-subrc <> 0.
    RAISE no_authorization.
  ENDIF.

  SELECT SINGLE agr_name FROM agr_define
    INTO lv_agr_name
    WHERE agr_name = lv_agr_name.
  IF sy-subrc <> 0.
    RAISE role_not_found.
  ENDIF.

* --- 1. lock ---
  CALL FUNCTION 'PRGN_ACTIVITY_GROUP_ENQUEUE'
    EXPORTING
      activity_group = lv_agr_name
      no_dialog      = 'X'          " CONFIRM IN SE37: safe headless
    IMPORTING
      new_request    = lv_request   " set if the role is transportable
    EXCEPTIONS
      foreign_lock   = 1
      OTHERS         = 2.
  IF sy-subrc = 1.
    RAISE role_locked.
  ELSEIF sy-subrc <> 0.
    RAISE update_failed.
  ENDIF.

* --- 2. backup (PRGN_DOWNLOAD_AGR) ---
*     Interface confirmed from SE37 on TS3. create_file_only = 'X' builds
*     the export in FILE_CONTENT without writing any file on the server
*     or opening a dialog; display_log = space suppresses the log popup.
*     User assignments are not exported (with_user_assignment default).
*     No automatic restore: PRGN_UPLOAD_AGR is file/GUI based (see header).
  CALL FUNCTION 'PRGN_DOWNLOAD_AGR'
    EXPORTING
      activity_group          = lv_agr_name
      with_authorization_data = 'X'
      display_log             = space
      create_file_only        = 'X'
    IMPORTING
      return                  = lt_return
    TABLES
      file_content            = role_backup
    EXCEPTIONS
      activity_group_does_not_exist = 1
      not_authorized                = 2
      OTHERS                        = 3.
  IF sy-subrc <> 0.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE backup_failed.
  ENDIF.

* --- 3. read current auth data ---
*     PRGN_CLEAR_BUFFER (no parameters, include LPRGNU09) resets all
*     GLOBAL_AGR_*_UPDATE flags and buffers so a stale buffer from an
*     earlier call in the same RFC session cannot be flushed by mistake.
  CALL FUNCTION 'PRGN_CLEAR_BUFFER'.

*     Confirmed interface: activity_group, no_texts, no_texts_save;
*     TABLES auth_data TYPE pt1250 ONLY. There is NO PT1251 parameter -
*     this FM returns auth headers and status, not field values. Field
*     values (object/field/low/high) go through
*     PRGN_1251_READ_FIELD_VALUES / PRGN_1251_SAVE_FIELD_VALUES (exist
*     on TS3, interfaces not read yet) - fill in the two marked calls.
  CALL FUNCTION 'PRGN_1250_READ_AUTH_DATA'
    EXPORTING
      activity_group = lv_agr_name
      no_texts       = 'X'
    TABLES
      auth_data      = lt_auth
    EXCEPTIONS
      no_data_available = 1
      OTHERS            = 2.
  IF sy-subrc <> 0.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE update_failed.
  ENDIF.

  CALL FUNCTION 'PRGN_1251_READ_FIELD_VALUES'
    EXPORTING
      activity_group    = lv_agr_name
    TABLES
      field_values      = lt_fields
    EXCEPTIONS
      no_data_available = 1
      OTHERS            = 2.
  IF sy-subrc <> 0.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE update_failed.
  ENDIF.

* --- 4. apply changes in memory (PT1251 rows) ---
*     PT1251 joins to PT1250 on object + auth + variant. Our input has
*     only object/field/low/high, so an add targets the FIRST
*     authorization instance of that object on the role. If the role has
*     none, raise OBJECT_NOT_ON_ROLE - creating a new auth-object
*     instance is out of scope for v2.
  LOOP AT authorization_values_delete INTO ls_del.
*   v2.3: drop the row. Do NOT set DELETED = 'X' here: on TS3 that made
*   PFCG show the field as "Inactive" (no check on the field at all,
*   and the added value was not active) - a security regression. The
*   first run that "failed" to delete failed because the database flush
*   (PRGN_UPDATE_DATABASE) was missing, not because dropping rows
*   does not work.
    DELETE lt_fields
      WHERE object = ls_del-object
        AND field  = ls_del-field
        AND low    = ls_del-low.
*   v2.5: a removal that matches nothing used to succeed silently (a
*   typo in a request looked like success). Fail instead.
    IF sy-subrc <> 0.
      CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
      CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
        EXPORTING activity_group = lv_agr_name.
      RAISE value_not_found.
    ENDIF.
*   Mark the parent auth as changed so PFCG regenerates it.
    LOOP AT lt_auth ASSIGNING <fs_auth> WHERE object = ls_del-object.
      <fs_auth>-modified = c_modified.
    ENDLOOP.
  ENDLOOP.

  LOOP AT authorization_values INTO ls_add.
    READ TABLE lt_auth INTO ls_auth WITH KEY object = ls_add-object.
    IF sy-subrc <> 0.
      CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
        EXPORTING activity_group = lv_agr_name.
      RAISE object_not_on_role.
    ENDIF.
*   v2.4: the field must already exist on that authorization. Without
*   this check a wrong FIELD (e.g. ACTVT value sent as DOKAR) is written
*   silently: seen on TS3, "02" landed on DOKAR instead of ACTVT.
    READ TABLE lt_fields TRANSPORTING NO FIELDS
      WITH KEY object  = ls_add-object
               auth    = ls_auth-auth
               variant = ls_auth-variant
               field   = ls_add-field.
    IF sy-subrc <> 0.
      CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
      CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
        EXPORTING activity_group = lv_agr_name.
      RAISE field_not_on_auth.
    ENDIF.
*   v2.5: adding a value that already exists wrote a duplicate row and
*   made profile generation fail on TS3 (data already committed by then).
    READ TABLE lt_fields TRANSPORTING NO FIELDS
      WITH KEY object  = ls_add-object
               auth    = ls_auth-auth
               variant = ls_auth-variant
               field   = ls_add-field
               low     = ls_add-low.
    IF sy-subrc = 0.
      CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
      CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
        EXPORTING activity_group = lv_agr_name.
      RAISE value_already_exists.
    ENDIF.
    CLEAR ls_field.
    ls_field-object  = ls_add-object.
    ls_field-auth    = ls_auth-auth.
    ls_field-variant = ls_auth-variant.
    ls_field-field   = ls_add-field.
    ls_field-low     = ls_add-low.
    ls_field-high    = ls_add-high.
*   TPR_STA_IN flags (confirmed components: MODIFIED, DELETED, COPIED,
*   NEU, NODE - all CHAR1 except NODE NUMC6): new value row is NEU.
    ls_field-neu      = 'X'.
    ls_field-modified = c_modified.
    APPEND ls_field TO lt_fields.
    READ TABLE lt_auth ASSIGNING <fs_auth>
      WITH KEY object = ls_add-object auth = ls_auth-auth.
    IF sy-subrc = 0.
      <fs_auth>-modified = c_modified.
    ENDIF.
  ENDLOOP.

* --- 5. save (field values, then auth headers) ---
  CALL FUNCTION 'PRGN_1251_SAVE_FIELD_VALUES'
    EXPORTING
      activity_group = lv_agr_name
    TABLES
      field_values   = lt_fields.

  CALL FUNCTION 'PRGN_1250_SAVE_AUTH_DATA'
    EXPORTING
      activity_group = lv_agr_name
    TABLES
      auth_data      = lt_auth
    EXCEPTIONS
      OTHERS         = 1.
  IF sy-subrc <> 0.
*   No automatic restore (see header); caller keeps ROLE_BACKUP.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE update_failed.
  ENDIF.

* v2.2: SAVE_AUTH_DATA / SAVE_FIELD_VALUES only fill the function
* group's global buffers (GLOBAL_AGR_1250/1251 + *_UPDATE flags); they
* never write the database (confirmed from their source on TS3 - the
* first run left AGR_1251 untouched). PRGN_UPDATE_DATABASE (no
* parameters, include LPRGNU48) flushes them: it tests
* global_agr_1251_update = 'X' and PERFORMs the DB update.
  CALL FUNCTION 'PRGN_UPDATE_DATABASE'
    EXCEPTIONS
      OTHERS = 1.
  IF sy-subrc <> 0.
    CALL FUNCTION 'PRGN_CLEAR_BUFFER'.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE update_failed.
  ENDIF.

* v2.1: commit the saved data BEFORE generating. The generator has
* rebuild_auth_data = 'X' by default and may re-read the role from the
* database, discarding uncommitted edits (first run: nothing persisted).
  COMMIT WORK AND WAIT.
  CALL FUNCTION 'PRGN_CLEAR_BUFFER'.

* --- 6. regenerate the profile ---
*     Without this the role definition changes but nothing takes effect
*     for any user until someone regenerates in PFCG.
*     Interface confirmed. Defaults worth knowing: rebuild_auth_data = 'X'
*     (rebuilds PT1250/PT1251-derived data - runs AFTER our save, so it
*     must not undo it: verify in sandbox) and
*     fill_empty_fields_with_star = 'X' (empty fields become '*', PFCG's
*     own behavior - do NOT change without security sign-off).
  CALL FUNCTION 'PRGN_AUTO_GENERATE_PROFILE_NEW'
    EXPORTING
      activity_group   = lv_agr_name
      no_dialog        = 'X'
      generate_profile = 'X'
      rebuild_auth_data = space
      request          = lv_request
    IMPORTING
      new_request      = lv_request
    TABLES
      return           = lt_gen_ret
    EXCEPTIONS
      activity_group_does_not_exist = 1
      activity_group_enqueued       = 2
      no_auth_for_role_change       = 3
      no_auth_for_gen               = 4
      no_auths                      = 5
      open_auths                    = 6
      too_many_auths                = 7
      profgen_tables_not_updated    = 8
      error_when_generating_profile = 9
      OTHERS                        = 10.
  IF sy-subrc <> 0.
*   v2.5: hand the generator's own messages back (data is ALREADY
*   committed at this point: role changed, profile stale).
    APPEND LINES OF lt_gen_ret TO return.
    CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
      EXPORTING activity_group = lv_agr_name.
    RAISE profile_generation_failed.
  ENDIF.

  COMMIT WORK AND WAIT.

* --- 7. unlock ---
  CALL FUNCTION 'PRGN_ACTIVITY_GROUP_DEQUEUE'
    EXPORTING activity_group = lv_agr_name.
