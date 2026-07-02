import { workflow, node, trigger, ifElse, newCredential, expr } from '@n8n/workflow-sdk';

const GHL = { httpBearerAuth: newCredential('HighLevel Bearer Auth', 'GS6kXBLE1ooZqLap') };
const V_CONTACTS = { name: 'Version', value: '2021-07-28' };
const V_CONV = { name: 'Version', value: '2021-04-15' };
const H_CT = { name: 'Content-Type', value: 'application/json' };
const H_ACCEPT = { name: 'Accept', value: 'application/json' };
const RETRY = { retryOnFail: true, maxTries: 3, waitBetweenTries: 5000 };

const wh = trigger({
  type: 'n8n-nodes-base.webhook', version: 2.1,
  config: { name: 'S4.5 Webhook', parameters: { httpMethod: 'POST', path: 's4-5-seinfeld-nurture', options: {} } },
  output: [{ body: { contact_id: 'abc', enrollment_reason: 'engaged-unbooked', sequence_position: '' } }]
});

const normalize = node({
  type: 'n8n-nodes-base.set', version: 3.4,
  config: { name: 'Normalize Input', parameters: {
    mode: 'manual', includeOtherFields: true,
    assignments: { assignments: [
      { id: 'a1', name: 'contactId', value: expr('{{ $json.body?.contact_id ?? $json.contact_id ?? $json.body?.contactId ?? $json.contactId }}'), type: 'string' },
      { id: 'a2', name: 'enrollment_reason', value: expr('{{ $json.body?.enrollment_reason ?? $json.enrollment_reason ?? "" }}'), type: 'string' },
      { id: 'a3', name: 'inboundPosition', value: expr('{{ $json.body?.sequence_position ?? $json.sequence_position ?? "" }}'), type: 'string' },
      { id: 'a4', name: 'enteredAt', value: expr('{{ $now.toISO() }}'), type: 'string' }
    ] } } },
  output: [{ contactId: 'abc', enrollment_reason: 'engaged-unbooked', inboundPosition: '', enteredAt: '2026-07-02T00:00:00.000Z' }]
});

const getEntry = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Get Contact (Entry)', onError: 'continueErrorOutput', parameters: {
    method: 'GET',
    url: expr('https://services.leadconnectorhq.com/contacts/{{ $json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair',
    headerParameters: { parameters: [V_CONTACTS, H_ACCEPT] }, options: {} },
    ...RETRY, credentials: GHL },
  output: [{ contact: { id: 'abc', email: 'a@b.com', tags: [], customFields: [] } }]
});

const notFound = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Contact Not Found - Notify Mark' }, output: [{}] });

const parseEntry = node({
  type: 'n8n-nodes-base.code', version: 2,
  config: { name: 'Parse Entry', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode:
    "const c = ($('Get Contact (Entry)').first().json.contact) || {};\n" +
    "const cf = c.customFields || [];\n" +
    "const getCF = (id) => { const f = cf.find(x => x.id === id); return f ? (f.value ?? f.field_value ?? '') : ''; };\n" +
    "const posRaw = getCF('apoe5TFnilPriJmIzvbo');\n" +
    "const existingPosition = parseInt(posRaw, 10);\n" +
    "return [{ json: {\n" +
    "  contactId: c.id,\n" +
    "  email: (c.email || ''),\n" +
    "  tags: (c.tags || []),\n" +
    "  existingPosition: Number.isFinite(existingPosition) ? existingPosition : null,\n" +
    "  enrollment_reason: $('Normalize Input').first().json.enrollment_reason\n" +
    "} }];" } },
  output: [{ contactId: 'abc', email: 'a@b.com', tags: [], existingPosition: null, enrollment_reason: 'engaged-unbooked' }]
});

const SUPPRESS = "['dnc','dnc-email','lp-dnc','p3:dnc','stop-seinfeld','stage:booked-main-appointment','stop-bot','pause-workflow','suppress-outbound','unsubscribed']";

const eligible = ifElse({ version: 2.2, config: { name: 'Eligible to Enroll?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'e1', leftValue: expr('{{ !(($json.tags||[]).some(t => ' + SUPPRESS + '.includes(t))) }}'), rightValue: true, operator: { type: 'boolean', operation: 'equals' } } ] } } } });

const removeActiveSuppressed = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Active Tags (Suppressed)', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const exitSuppressed = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Exit: Suppressed' }, output: [{}] });

const addActive = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Add Tags: active-s4.5, nurture-active', parameters: {
    method: 'POST', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const STAGE_TAGS = '["stage:solution-pitch","stage:vendor-comparison","buyer:vendor-comparison","stage:active-nurture-broadcast","stage:booked-main-appointment","stage:booked-review","stage:booking-qualification","stage:booking-review","stage:conversion-sequence","stage:customer-onboarding","stage:deferred","stage:education","stage:entry-bridge","stage:hot-call","stage:indoctrination","stage:long-term-nurture","stage:new-lead","stage:objection-handling","stage:post-appointment","stage:proposal-delivered","stage:re-engagement","stage:reactivation","stage:unresponsive","stage:booking-main","stage:cancellation-review","stage:closed-won","stage:fast-track","stage:lost","stage:appointment-rescue"]';

const removeStage = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Conflicting Stage Tags', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ' + STAGE_TAGS + ' } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const MUTEX_TAGS = '["active-e.0","active-e.2","active-e02-vc","active-s2.1","active-s2.5","active-s2.6","active-s3.0","active-s3.1","active-s4.0","active-s4.1","active-s4.2","active-s5.2","active-w0","active-w01","active-w02","active-w03","active-w04","active-w05","active-w06","active-w1","active-w07","active-w1.0","active-w1.1","active-w1.2","active-w10.0","active-w11.1","active-w11.2","active-w12.0","active-w12.1","active-w12.2","active-w12.3","active-w12.4","active-w12.5","active-w12.6","active-w12.7","active-w2.0","active-w2.1","active-w2.2","active-w3.0","active-w3.1","active-w3.2","active-w4.0","active-w4.1","active-w4.2","active-w5.1","active-w4.5","active-w5.2","active-w8.0","active-w9","active-w9.0","active-2.0","active-e.1","active-e.3","active-e.5","active-s1.0","active-s1.1","active-s1.2","active-s2.0","active-s2.2","active-s2.3","active-w-hdl2","active-w-hdl1","active-w11.1-customer-removed","active-w11.1-eject-applied","active-w11.1-lapsed-rerouted","active-w11.1-rep-callback-issued"]';

const removeMutex = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Conflicting Active Tags', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ' + MUTEX_TAGS + ' } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const updateMarketing = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Update Active Marketing Details', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "customFields": [ { "id": "VFSNtEqSUh5yX7RyktBj", "value": "f99fba97-6d2f-4fd6-966c-b5e5e36f8938" }, { "id": "5MmqueQgbVELUl8CpaMR", "value": $(\'Normalize Input\').first().json.enrollment_reason } ] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const assignRandy = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Assign to Randy Reece', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "assignedTo": "9YNXGEOajzmH9brXcLsy" } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const emailExists = ifElse({ version: 2.2, config: { name: 'Email Exists?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'em1', leftValue: expr('{{ (($(\'Parse Entry\').first().json.email)||"").length > 0 }}'), rightValue: true, operator: { type: 'boolean', operation: 'equals' } } ] } } } });

const removeActiveNoEmail = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Active Tags (No Email)', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const exitNoEmail = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Exit: No Email' }, output: [{}] });

const ensurePosition = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Ensure Sequence Position', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "customFields": [ { "id": "apoe5TFnilPriJmIzvbo", "value": ($(\'Parse Entry\').first().json.existingPosition || 1) }, { "id": "PMq1AzXFX3nudZgNFxbw", "value": "No" } ] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const lpGenerate = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'LP Generate Request', parameters: {
    method: 'POST', url: 'https://lp-mcp-production.up.railway.app/api/agentic/nurture/generate',
    sendHeaders: true, specifyHeaders: 'keypair',
    headerParameters: { parameters: [ { name: 'Authorization', value: expr('Bearer {{ $env.MESSAGE_ENGINE_TOKEN }}') } ] },
    sendBody: true, contentType: 'form-urlencoded', specifyBody: 'keypair',
    bodyParameters: { parameters: [
      { name: 'contact_id', value: expr('{{ $(\'Parse Entry\').first().json.contactId }}') },
      { name: 'workflow_code', value: 'S4.5' },
      { name: 'sequence_position', value: expr('{{ $(\'Parse Entry\').first().json.existingPosition || 1 }}') },
      { name: 'channel', value: 'email' },
      { name: 'enrollment_reason', value: expr('{{ $(\'Normalize Input\').first().json.enrollment_reason }}') }
    ] }, options: {} }, ...RETRY, credentials: GHL },
  output: [{ ok: true }]
});

const wait5 = node({ type: 'n8n-nodes-base.wait', version: 1.1, config: { name: 'Wait 5 Minutes', parameters: { amount: 5, unit: 'minutes' } }, output: [{}] });

const getPoll = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Get Contact (Poll)', parameters: {
    method: 'GET', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_ACCEPT] }, options: {} }, ...RETRY, credentials: GHL },
  output: [{ contact: { id: 'abc', tags: [], customFields: [] } }]
});

const parsePoll = node({
  type: 'n8n-nodes-base.code', version: 2,
  config: { name: 'Parse Poll State', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode:
    "const c = ($('Get Contact (Poll)').first().json.contact) || {};\n" +
    "const cf = c.customFields || [];\n" +
    "const getCF = (id) => { const f = cf.find(x => x.id === id); return f ? (f.value ?? f.field_value ?? '') : ''; };\n" +
    "const pos = parseInt(getCF('apoe5TFnilPriJmIzvbo'), 10) || 0;\n" +
    "const psVal = (getCF('vrAbErigvAzLCU9jj7kT') || '').toString().trim();\n" +
    "const waitHours = parseFloat(getCF('h6OyxuBTv7w7ieub1P9y'));\n" +
    "return [{ json: {\n" +
    "  contactId: c.id,\n" +
    "  sendReady: (getCF('PMq1AzXFX3nudZgNFxbw') || '').toString(),\n" +
    "  tags: (c.tags || []),\n" +
    "  position: pos,\n" +
    "  nextPosition: pos + 1,\n" +
    "  hasPS: psVal.length > 0,\n" +
    "  nextWaitHours: (Number.isFinite(waitHours) && waitHours > 0) ? waitHours : 48\n" +
    "} }];" } },
  output: [{ contactId: 'abc', sendReady: 'Yes', tags: [], position: 1, nextPosition: 2, hasPS: false, nextWaitHours: 48 }]
});

const sendReady = ifElse({ version: 2.2, config: { name: 'Send Ready?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'sr1', leftValue: expr('{{ $json.sendReady }}'), rightValue: 'Yes', operator: { type: 'string', operation: 'equals' } } ] } } } });

const timedOut = ifElse({ version: 2.2, config: { name: 'Timed Out (24h)?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'to1', leftValue: expr('{{ $now.diff($(\'Normalize Input\').first().json.enteredAt, "hours").hours >= 24 }}'), rightValue: true, operator: { type: 'boolean', operation: 'equals' } } ] } } } });

const waitPoll = node({ type: 'n8n-nodes-base.wait', version: 1.1, config: { name: 'Wait 30 Minutes (Poll)', parameters: { amount: 30, unit: 'minutes' } }, output: [{}] });

const addStuck = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Add Tag: s4.5-stuck', parameters: {
    method: 'POST', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["s4.5-stuck"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const removeActiveStuck = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Active Tags (Stuck)', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Entry\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const stuckNotify = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Exit: Stuck - Notify Mark' }, output: [{}] });

const stillEligible = ifElse({ version: 2.2, config: { name: 'Still Eligible (Fresh)?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'se1', leftValue: expr('{{ !(($(\'Parse Poll State\').first().json.tags||[]).some(t => ' + SUPPRESS + '.includes(t))) }}'), rightValue: true, operator: { type: 'boolean', operation: 'equals' } } ] } } } });

const removeActiveFresh = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Active Tags (Fresh Suppressed)', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const exitFreshSuppressed = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Exit: Fresh Suppressed' }, output: [{}] });

const buildEmail = node({
  type: 'n8n-nodes-base.code', version: 2,
  config: { name: 'Build Email HTML', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode:
    "const s = $('Parse Poll State').first().json;\n" +
    "const hasPS = !!s.hasPS;\n" +
    "const psBlock = hasPS ? (\n" +
    "  '<tr><td class=\"p-sm\" style=\"padding:18px 28px 8px 28px;\">' +\n" +
    "  '<div class=\"ps-divider\" style=\"border-top:1px solid #e5e5e5; padding-top:18px; font:15px/1.6 -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; color:#555555;\">' +\n" +
    "  '<strong style=\"color:#122739;\">P.S.</strong> {{contact.ai_email_ps_draft}}</div></td></tr>'\n" +
    ") : '';\n" +
    "const html = '<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">' +\n" +
    "  '<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">' +\n" +
    "  '<title>Reece Windows &amp; Doors</title>' +\n" +
    "  '<style>p{margin:0 0 16px 0;padding:0;} table{border-collapse:collapse;} a{text-decoration:underline;} @media screen and (max-width:640px){.container{width:100%!important;}.p-sm{padding-left:20px!important;padding-right:20px!important;}}</style>' +\n" +
    "  '</head><body style=\"margin:0;padding:0;\">' +\n" +
    "  '<div style=\"display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;opacity:0;color:transparent;\">{{contact.ai_email_preview_draft}}</div>' +\n" +
    "  '<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\"><tr><td align=\"center\" style=\"padding:16px 12px;\">' +\n" +
    "  '<table role=\"presentation\" class=\"container\" width=\"640\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" style=\"width:640px;\">' +\n" +
    "  '<tr><td class=\"p-sm\" style=\"padding:5px 24px 0 24px; font:16px/1.6 -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; color:#333333;\">' +\n" +
    "  '<div style=\"margin:0 0 20px; white-space:normal;\">{{contact.ai_email_body_draft}}</div>' +\n" +
    "  '<p style=\"margin:0; font-weight:400; color:#122739;\">{{custom_values.founder_name}}</p>' +\n" +
    "  '<p style=\"margin:0; font-weight:600; color:#122739;\">Reece Windows &amp; Doors</p>' +\n" +
    "  '</td></tr>' + psBlock +\n" +
    "  '<tr><td align=\"center\" class=\"p-sm\" style=\"padding:18px 28px 6px 28px; font:12px/1.6 -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; color:#666666;\"><em>Protecting families since 1972</em></td></tr>' +\n" +
    "  '<tr><td align=\"center\" class=\"p-sm\" style=\"padding:6px 28px 24px 28px; font:12px/1.6 -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; color:#888888;\">' +\n" +
    "  '<div style=\"color:#888888;\">{{location.address}}, {{location.city}}, {{location.state}} {{location.postal_code}}</div>' +\n" +
    "  '<div style=\"margin-top:8px; color:#888888;\"><a href=\"{{email.unsubscribe_link}}\" style=\"color:#888888; text-decoration:underline;\">Unsubscribe</a> &nbsp;&bull;&nbsp; &copy; {{right_now.year}} {{location.name}}</div>' +\n" +
    "  '</td></tr></table></td></tr></table></body></html>';\n" +
    "return [{ json: { type: 'Email', contactId: s.contactId, subject: '{{contact.ai_email_subject_draft}}', html: html } }];" } },
  output: [{ type: 'Email', contactId: 'abc', subject: '{{contact.ai_email_subject_draft}}', html: '<html></html>' }]
});

const sendEmail = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Send Email (Conversations)', parameters: {
    method: 'POST', url: 'https://services.leadconnectorhq.com/conversations/messages',
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONV, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "type": "Email", "contactId": $json.contactId, "subject": $json.subject, "html": $json.html, "emailFrom": "Randy Reece <randy@getreecewindows.com>" } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ messageId: 'm1' }]
});

const lpEngagement = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'LP Engagement (email_sent)', parameters: {
    method: 'POST', url: 'https://lp-mcp-production.up.railway.app/api/agentic/messages/engagement',
    sendHeaders: true, specifyHeaders: 'keypair',
    headerParameters: { parameters: [ { name: 'Authorization', value: expr('Bearer {{ $env.MESSAGE_ENGINE_TOKEN }}') }, H_CT ] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "generation_id": ($(\'Parse Poll State\').first().json.contactId), "event": "email_sent" } }}'), options: {} }, ...RETRY },
  output: [{ ok: true }]
});

const resetGate = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Reset Send Gate (No)', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "customFields": [ { "id": "PMq1AzXFX3nudZgNFxbw", "value": "No" } ] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const clearDrafts = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Clear Draft Fields', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "customFields": [ { "id": "vrAbErigvAzLCU9jj7kT", "value": "" }, { "id": "WP3BnkdAsINf13CCYGbr", "value": "" }, { "id": "C8mSMxWqXGr1HvxrImyx", "value": "" }, { "id": "hmmFUscWqxH1On6WPCP3", "value": "" }, { "id": "tDAsxwtvks6DEmwx4bFK", "value": "" } ] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});

const rotationComplete = ifElse({ version: 2.2, config: { name: 'Rotation Complete (>=12)?', parameters: {
  conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 }, combinator: 'and',
    conditions: [ { id: 'rc1', leftValue: expr('{{ $(\'Parse Poll State\').first().json.position >= 12 }}'), rightValue: true, operator: { type: 'boolean', operation: 'equals' } } ] } } } });

const addRotationTag = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Add Tag: s4.5-rotation-completed', parameters: {
    method: 'POST', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["s4.5-rotation-completed"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const removeActiveComplete = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Remove Active Tags (Complete)', parameters: {
    method: 'DELETE', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}/tags'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "tags": ["active-s4.5","nurture-active"] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const completeRouted = node({ type: 'n8n-nodes-base.noOp', version: 1, config: { name: 'Completion via Decision Engine (no hardcoded dest)' }, output: [{}] });

const updateNextPosition = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Increment Sequence Position', parameters: {
    method: 'PUT', url: expr('https://services.leadconnectorhq.com/contacts/{{ $(\'Parse Poll State\').first().json.contactId }}'),
    authentication: 'genericCredentialType', genericAuthType: 'httpBearerAuth',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [V_CONTACTS, H_CT, H_ACCEPT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "customFields": [ { "id": "apoe5TFnilPriJmIzvbo", "value": $(\'Parse Poll State\').first().json.nextPosition } ] } }}'), options: {} }, ...RETRY, credentials: GHL },
  output: [{ succeeded: true }]
});
const waitDynamic = node({ type: 'n8n-nodes-base.wait', version: 1.1, config: { name: 'Wait Dynamic (Next Cycle)', parameters: { amount: expr('{{ $(\'Parse Poll State\').first().json.nextWaitHours }}'), unit: 'hours' } }, output: [{}] });
const selfFire = node({
  type: 'n8n-nodes-base.httpRequest', version: 4.2,
  config: { name: 'Self-Fire Next Cycle', parameters: {
    method: 'POST', url: 'https://n8n-main-instance-production-981e.up.railway.app/webhook/s4-5-seinfeld-nurture',
    sendHeaders: true, specifyHeaders: 'keypair', headerParameters: { parameters: [H_CT] },
    sendBody: true, contentType: 'json', specifyBody: 'json',
    jsonBody: expr('{{ { "contact_id": $(\'Parse Poll State\').first().json.contactId, "sequence_position": $(\'Parse Poll State\').first().json.nextPosition, "enrollment_reason": $(\'Normalize Input\').first().json.enrollment_reason } }}'), options: {} }, ...RETRY },
  output: [{ ok: true }]
});

export default workflow('s4-5-v2-seinfeld', 'S4.5 v2 — Agentic Seinfeld Nurture')
  .add(wh)
  .to(normalize)
  .to(getEntry.onError(notFound))
  .to(parseEntry)
  .to(eligible
    .onFalse(removeActiveSuppressed.to(exitSuppressed))
    .onTrue(addActive
      .to(removeStage)
      .to(removeMutex)
      .to(updateMarketing)
      .to(assignRandy)
      .to(emailExists
        .onFalse(removeActiveNoEmail.to(exitNoEmail))
        .onTrue(ensurePosition
          .to(lpGenerate)
          .to(wait5)
          .to(getPoll)
          .to(parsePoll)
          .to(sendReady
            .onTrue(stillEligible
              .onFalse(removeActiveFresh.to(exitFreshSuppressed))
              .onTrue(buildEmail
                .to(sendEmail)
                .to(lpEngagement)
                .to(resetGate)
                .to(clearDrafts)
                .to(rotationComplete
                  .onTrue(addRotationTag.to(removeActiveComplete).to(completeRouted))
                  .onFalse(updateNextPosition.to(waitDynamic).to(selfFire))
                )
              )
            )
            .onFalse(timedOut
              .onTrue(addStuck.to(removeActiveStuck).to(stuckNotify))
              .onFalse(waitPoll.to(getPoll))
            )
          )
        )
      )
    )
  );
