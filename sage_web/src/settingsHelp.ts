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
