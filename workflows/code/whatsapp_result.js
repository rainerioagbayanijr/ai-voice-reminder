// API acceptance is not a delivery/read receipt. Never retry an ambiguous send.
const response = $json;
const messageId = response.messages?.[0]?.id;
const accepted = !response.error && typeof messageId === 'string' && messageId.startsWith('wamid.');
return { json: {
  channel: 'whatsapp',
  status: accepted ? 'submitted' : 'unknown',
  message_id: accepted ? messageId : null,
  automatic_retry: false,
  next_step: accepted
    ? 'Check your verified test phone. Meta accepted this message; delivery and playback are not confirmed.'
    : 'Inspect the Send WhatsApp Audio node and your test phone before any manual retry. Submission may have succeeded.'
}};
