// API acceptance is not a delivery/read receipt. Never retry an ambiguous send.
const response = $json.body || $json;
const httpStatus = $json.statusCode;
const messageId = response.messages?.[0]?.id;
const accepted = !response.error && typeof messageId === 'string' &&
  /^wamid\.[A-Za-z0-9_=+./:-]{1,500}$/.test(messageId);
// Only explicit, recognized rate-limit rejections qualify for a later retry.
const limited = !accepted && [400, 429].includes(httpStatus) &&
  [130429, 131056].includes(response.error?.code);
const rejected = !accepted && !limited && !!response.error &&
  [400, 401, 403, 404, 405, 410, 413, 415, 422].includes(httpStatus);
const status = accepted ? 'submitted' : limited ? 'failed' : rejected ? 'rejected' : 'unknown';
return { json: {
  channel: 'whatsapp',
  status,
  error_code: accepted ? null : limited ? 'provider_rate_limited' :
    rejected ? 'provider_rejected' : 'submission_uncertain',
  message_id: accepted ? messageId : null,
  automatic_retry: limited,
  next_step: accepted
    ? 'Check your verified test phone. Meta accepted this message; delivery and playback are not confirmed.'
    : 'Inspect the Send WhatsApp Audio node and your test phone before any manual retry. Submission may have succeeded.'
}};
