// Recheck after synthesis/upload; neither TTS nor the upload opens a reply window.
const config = $('Validate Demo Setup').first().json;
const age = Date.now() - Date.parse(config.last_hello_at_utc);
if (!Number.isFinite(age) || age < 0 || age >= 24 * 60 * 60 * 1000 - 30000) {
  throw new Error('Reply window expired during preparation. No send was attempted. Send a fresh Hello and run again.');
}
if (typeof $json.id !== 'string' || !/^[0-9]{1,64}$/.test($json.id)) {
  throw new Error('Meta did not return a valid uploaded media ID. No send was attempted.');
}
return { json: {
  messaging_product: 'whatsapp',
  recipient_type: 'individual',
  to: config.test_recipient,
  type: 'audio',
  audio: { id: $json.id }
}};
