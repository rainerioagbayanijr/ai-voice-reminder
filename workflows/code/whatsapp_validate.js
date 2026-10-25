// One fictional sample and one operator-verified Meta test recipient per manual run.
const config = $json;
const windowSource = config.window_source || 'manual';
if (!['manual', 'webhook'].includes(windowSource)) {
  throw new Error('Set window_source to manual or webhook; it must match the backend setting.');
}
if (!['test', 'customer'].includes(config.routing_mode)) {
  throw new Error('Set routing_mode to test or customer. Default to test.');
}
if (typeof config.institution_id !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(config.institution_id)) {
  throw new Error('Set a stable institution_id; changing it creates a different reminder identity.');
}
if (config.routing_mode === 'customer' && config.input_mode !== 'csv') {
  throw new Error('Customer routing requires CSV input with each customer phone and a recent incoming message.');
}
if (!['single', 'csv'].includes(config.input_mode)) {
  throw new Error('Set input_mode to csv or single in Demo Settings.');
}
if (!['preview', 'send'].includes(config.mode)) {
  throw new Error('Mode must be preview or send. Start with preview.');
}
if (typeof config.first_name !== 'string' ||
    !/^[\p{L}\p{M} '\u2019-]{1,60}$/u.test(config.first_name.trim())) {
  throw new Error('Enter a sample first name containing letters, spaces, apostrophes or hyphens.');
}
for (const field of ['agent_name', 'bank_name']) {
  if (typeof config[field] !== 'string' || !config[field].trim() ||
      config[field].trim().length > 100 || /[\p{C}<>]/u.test(config[field])) {
    throw new Error('Set ' + field + ' in Demo Settings to plain text of 1 to 100 characters.');
  }
}
if (typeof config.due_date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(config.due_date)) {
  throw new Error('Set due_date in Demo Settings using YYYY-MM-DD.');
}
const recipient = typeof config.test_recipient === 'string'
  ? config.test_recipient.trim().replace(/^\+/, '') : '';
if (config.mode === 'send') {
  if (config.routing_mode === 'test') {
  if (config.meta_test_number_confirmed !== true || config.recipient_verified !== true) {
    throw new Error('Confirm the sender is Meta\'s developer test number and the recipient is your own verified, allowlisted phone.');
  }
  if (!/^[1-9][0-9]{7,14}$/.test(recipient)) {
    throw new Error('Set test_recipient to your verified WhatsApp phone with country code, without spaces.');
  }
  }
  if (typeof config.phone_number_id !== 'string' || !/^[0-9]{5,32}$/.test(config.phone_number_id)) {
    throw new Error('Copy the Phone Number ID from Meta API Setup. This is an ID, not the displayed phone number.');
  }
  if (typeof config.graph_api_version !== 'string' ||
      !/^v[0-9]{2,3}\.0$/.test(config.graph_api_version)) {
    throw new Error('Copy the Graph API version from the sample request in your Meta dashboard, such as vXX.0.');
  }
  if (config.routing_mode === 'test' && windowSource === 'manual') {
  if (typeof config.last_hello_at_utc !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(config.last_hello_at_utc)) {
    throw new Error('Send Hello from your verified phone first, then enter its actual UTC time in last_hello_at_utc.');
  }
  const age = Date.now() - Date.parse(config.last_hello_at_utc);
  if (!Number.isFinite(age) || age < 0 || age >= 24 * 60 * 60 * 1000 - 120000) {
    throw new Error('The recorded Hello is invalid, in the future, or too close to/outside the 24-hour reply window. Send a fresh Hello.');
  }
  }
}
return { json: {
  input_mode: config.input_mode,
  status: 'eligible',
  mode: config.mode,
  routing_mode: config.routing_mode,
  window_source: windowSource,
  institution_id: config.institution_id,
  test_recipient: recipient,
  phone_number_id: config.phone_number_id,
  graph_api_version: config.graph_api_version,
  last_hello_at_utc: config.last_hello_at_utc,
  voice_request: {
    customer_id: 'WHATSAPP-DEMO',
    first_name: config.first_name.trim(),
    bank_name: config.bank_name.trim(),
    agent_name: config.agent_name.trim(),
    due_date: config.due_date
  }
}};
