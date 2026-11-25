// Help text for every setting in sage_api's settings_store.DEFAULTS.
// A backend test checks that this list and DEFAULTS name the same keys.
export interface SettingHelp {
  summary: string        // what it does, in one or two sentences
  format?: string        // what a valid value looks like
  fallback: string       // the default, as shown to the admin
  effect?: string        // when a change takes effect, or what happens at the limit
}

export const SETTINGS_HELP: Record<string, SettingHelp> = {
  'providers.anthropic_api_key': {
    summary: 'API key Sage uses to call Claude. It is stored encrypted and never shown again.',
    format: 'The key text from the Anthropic console. Saving a new value replaces the old one.',
    fallback: 'Not set',
    effect: 'Without a key, Claude is not offered when a user starts a chat.',
  },
  'providers.openai_api_key': {
    summary: 'API key Sage uses to call GPT. It is stored encrypted and never shown again.',
    format: 'The key text from the OpenAI dashboard. Saving a new value replaces the old one.',
    fallback: 'Not set',
    effect: 'Without a key, GPT is not offered when a user starts a chat.',
  },
  'providers.models': {
    summary: 'The models users can pick for a chat, per provider.',
    format: 'JSON object: provider id ("anthropic" or "openai") to a list of model ids.',
    fallback: '{"anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"], "openai": ["gpt-5"]}',
    effect: 'A provider also needs its API key before its models appear. Existing chats keep working until someone changes their model.',
  },
  'providers.max_tokens': {
    summary: 'The most tokens the model may write in one reply.',
    format: 'A whole number.',
    fallback: '4096',
    effect: 'A reply that hits the limit is cut off. This is a per-reply size, not a usage limit.',
  },
  'agent.max_turns': {
    summary: 'How many times the model may be called in one run. It stops a run that keeps calling tools in a loop.',
    format: 'A whole number.',
    fallback: '10',
    effect: 'A run that reaches it ends as failed with "max_turns reached". It is a safety cap, not a usage limit.',
  },
  'wait.backoff': {
    summary: 'How often a waiting workflow checks SAP, for example while a background job runs.',
    format: 'JSON list of [elapsed seconds up to, seconds between checks]. The first pair whose limit is not yet passed applies. The default checks every 10 s in the first minute, then every 1 min, 5 min, 15 min and 1 h.',
    fallback: '[[60,10],[300,60],[3600,300],[10800,900],[86400,3600]]',
    effect: 'Applies to runs the next time they wake up.',
  },
  'wait.max_wait': {
    summary: 'How long a workflow may wait for SAP before it gives up.',
    format: 'Seconds, as a whole number.',
    fallback: '86400 (24 hours)',
    effect: 'A run that waits longer fails as timed out. Individual steps, such as waiting for a note download, can set a shorter limit.',
  },
  'sap.rowcount_cap': {
    summary: 'The most rows one table read returns from SAP.',
    format: 'A whole number.',
    fallback: '5000',
    effect: 'A larger result is cut at the cap and marked as truncated, so the workflow and the model know rows are missing.',
  },
  'health.max_age': {
    summary: 'How long a health check result stays fresh.',
    format: 'Seconds, as a whole number.',
    fallback: '86400 (24 hours)',
    effect: 'When a workflow is about to run on a system and its last check is older than this, Sage checks again first. A failed check stops the run.',
  },
  'workflows.disabled': {
    summary: 'Workflows hidden from the model on every system.',
    format: 'JSON list of workflow names, for example ["sap_readiness_check"].',
    fallback: '[] (none disabled)',
    effect: 'The Workflows page changes this list when you disable or enable a workflow, so you rarely need to edit it here.',
  },
  'addon.protected_components': {
    summary: 'Software components the add-on uninstall guide refuses to plan a removal for.',
    format: 'JSON list of SAP component names, for example ["SAP_BASIS", "S4CORE"].',
    fallback: 'The twelve core S/4HANA components: SAP_BASIS, SAP_ABA, SAP_GWFND, SAP_UI, S4CORE, S4COREOP, S4DEPREC, S4FND, EA-DFPS, EA-PS, FI-CAX, SAP_BW.',
    effect: 'Read when a guide starts. A listed component is reported as protected and gets no work order. Remove a name only if you are sure the component is not core on your systems.',
  },
  'email.enabled': {
    summary: 'Turns the sending of state emails on or off.',
    format: 'true or false.',
    fallback: 'false (no email is sent).',
    effect: 'Used when a workflow changes state and an email group is tagged for it. Turn it on after you set the mail server and the from address, then send a test email on the Email groups page.',
  },
  'email.smtp_host': {
    summary: 'The mail server (SMTP) Sage sends through.',
    format: 'A host name, for example "smtp.example.com".',
    fallback: 'Empty (email cannot be sent).',
    effect: 'Read each time an email is sent.',
  },
  'email.smtp_port': {
    summary: 'The port of the mail server.',
    format: 'A whole number: usually 587 for STARTTLS, 465 for SSL, 25 for none.',
    fallback: '587',
    effect: 'Read each time an email is sent.',
  },
  'email.security': {
    summary: 'How the connection to the mail server is protected.',
    format: '"starttls", "ssl" or "none". The server certificate is always checked for starttls and ssl.',
    fallback: '"starttls"',
    effect: 'Use "none" only for a relay inside a trusted network: the login and the mail travel unprotected.',
  },
  'email.smtp_user': {
    summary: 'The user Sage logs in to the mail server with.',
    format: 'A user name, or empty when the server needs no login.',
    fallback: 'Empty (no login).',
    effect: 'Used together with the password.',
  },
  'email.smtp_password': {
    summary: 'The password for the mail server user.',
    format: 'A text value. Stored encrypted, and never shown again once saved.',
    fallback: 'Not set.',
    effect: 'Used together with the user.',
  },
  'email.from_address': {
    summary: 'The address emails are sent from.',
    format: 'An email address, for example "sage@example.com".',
    fallback: 'Empty (email cannot be sent).',
    effect: 'The recipients are hidden from each other: every email is addressed to this address and the group members get a blind copy.',
  },
  'email.reminder_minutes': {
    summary: 'How often a lasting problem is mailed again.',
    format: 'Minutes, as a whole number. 0 turns reminders off.',
    fallback: '60',
    effect: 'When a status workflow keeps finding the same bad result (for example SUM in ERROR), the first email goes out at once. While it lasts, a reminder goes out every this many minutes, to the groups tagged for that result. Only results a workflow lists for reminders repeat.',
  },
  'email.digest_hour_utc': {
    summary: 'The hour of the day (UTC) when daily digests are sent.',
    format: 'A whole number from 0 to 23.',
    fallback: '8',
    effect: 'A group tagged for a daily digest gets one email a day, from this hour on, with all events since the last one. Hourly digests ignore this setting.',
  },
  'rolechange.max_entries': {
    summary: 'The most changes one role-change request may hold.',
    format: 'A whole number.',
    fallback: '50',
    effect: 'The user-role review and the user-role change refuse a larger request. Raise it only if people need bigger batches.',
  },
  'rolechange.policy': {
    summary: 'The policy a role authorization change request must meet before Sage will apply it.',
    format: 'JSON object. "max_changes_per_request" is the most changes in one request. "allowed_activity_levels" lists the ACTVT codes a request may add or change. "restricted_objects" lists authorization objects, each with a "reason", that always need an exception.',
    fallback: 'At most 50 changes, activity codes 01, 02, 03, 06, 16 and 70, and the objects S_DEVELOP, S_ADMI_FCD and S_USER_GRP restricted.',
    effect: 'Read when a review or change starts. A request that breaks the policy is refused and has to go through the security team and PFCG. SAP standard roles (SAP_*) and the value * are always refused.',
  },
  'sod.matrix': {
    summary: 'The segregation-of-duties rules the user SoD check workflow compares the roles of a user against.',
    format: 'JSON object with "conflicts", a list of rules. Each rule has "id", "object_1" and "object_2" (more sides as "object_3" and so on), "description", "risk_level" (CRITICAL, HIGH, MEDIUM or LOW) and "recommended_action". A side is an authorization object or a transaction code. Add "activity_1", "activity_2" (for example "01,02") to count a side only when the role grants one of those ACTVT codes. Names may use letters, digits and _ / . $ # @ -.',
    fallback: 'Three rules: posting and payment approval (SOD-001), purchase order creation and approval (SOD-002), development and administration (SOD-006).',
    effect: 'Read when a check starts. A rule fires when the user holds every side, even across different roles. A transaction code with a wildcard in a role is not matched.',
  },
  'readiness.prerequisite_notes': {
    summary: 'The SAP Notes the Readiness Check workflow needs on a system before it starts the analysis job.',
    format: 'JSON object. "notes" lists the notes (number, optional remark, optional "conditional": true, which is reported but never blocks). "download_wait_seconds" and "download_poll_seconds" control waiting for missing notes. "require_implemented" blocks on notes that are downloaded but not implemented. "implementation_status" names the SAP table, field and values that mean implemented.',
    fallback: 'Eight notes, wait 600 s, check every 15 s, implemented notes required (table CWBNTCUST, field PRSTATUS, value E).',
    effect: 'Read when a run starts. A run already in progress keeps the list it started with.',
  },
}
