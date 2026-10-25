# Speech providers

`TTS_PROVIDER=edge` remains the default. No ElevenLabs account/key is required for the current
prototype. Switching providers is a backend configuration change, not an n8n workflow change.
The same templates, customer validation, ledger, MP3 endpoint, OGG/Opus conversion and delivery
nodes are reused. Voice/provider changes do not bypass reminder duplicate protection.

## Architecture

```text
CSV → n8n → FastAPI/TTSService → configured SpeechProvider → bounded MP3
                                              ├─ EdgeTTSProvider (default)
                                              └─ ElevenLabsProvider (optional)
MP3 → email attachment OR FFmpeg → OGG/Opus → WhatsApp voice note
```

`app/services/tts.py` owns rendering, the deadline, concurrency and final MP3 validation. The
`SpeechProvider` protocol in `app/services/providers/base.py` defines option validation and
`synthesize(text, options) -> bytes`. Providers receive rendered text and speech options rather
than contact details or tracking tokens. Both implementations cap audio while reading it.
The existing `TTSService.generate(VoiceRequest)` interface remains available to other Python code.

Provider selection happens at startup, from environment configuration. HTTP callers cannot select
a provider or API host. The factory chooses exactly one provider; there is no automatic failover,
silent switch to a paid API, or provider-level retry loop. Existing n8n retries remain bounded.
Upstream failures map to sanitized 502 responses; the common timeout maps to 504. Unsupported
voice/prosody maps to 422 before making a speech request. Credentials and upstream bodies are not
returned to callers or written to application logs.

## Keep Edge active now

```dotenv
TTS_PROVIDER=edge
VOICE=fil-PH-BlessicaNeural
ALLOWED_VOICES=en-US-JennyNeural,en-US-AriaNeural,fil-PH-BlessicaNeural
LANGUAGE=fil
RATE=-15%
VOLUME=-5%
```

This retains the existing Filipino voice, English date words and script. Edge TTS still uses
Microsoft's online speech service; the interface does not turn it into an offline engine.

## Enable ElevenLabs later

Supply your own credentials, account voice ID and a model that supports your intended language:

```dotenv
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your-private-key
ELEVENLABS_VOICE_ID=your-voice-id
ELEVENLABS_MODEL_ID=your-model-id
ELEVENLABS_ALLOWED_VOICES=
ELEVENLABS_LANGUAGE_CODE=
ELEVENLABS_SPEED=0.85
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.75
LANGUAGE=fil
```

The IDs above are placeholders. Startup fails if key, voice or model is missing. A blank voice
allowlist permits only the configured default ID; add comma-separated IDs to allow request-level
voice overrides. Edge voice names are not ElevenLabs voice IDs. Remove/update any CSV or API
voice overrides when changing engines.

- `LANGUAGE` selects our `en`/`fil` script templates. It does not guarantee provider/model support.
  Preview and listen with the selected account voice/model before sending.
- Optional `ELEVENLABS_LANGUAGE_CODE` is a two-letter ISO code, supplied only when explicitly set.
  It is rejected for `eleven_multilingual_v2`, which does not support that parameter. The template
  code `fil` is not forwarded automatically; verify the model's supported language codes.
- `ELEVENLABS_SPEED` accepts 0.7–1.2. A request's `rate` percentage overrides it by mapping to
  `1 + rate/100` (for example `-15%` becomes 0.85); unsupported values are rejected, not clamped.
  Actual pacing/tone differs between engines and needs listening review.
- `VOICE`, `ALLOWED_VOICES`, `RATE` and `VOLUME` are Edge defaults. ElevenLabs uses its own
  defaults above; its default volume is neutral. Explicit nonzero `volume` requests are rejected
  because this adapter does not implement a provider volume control or postprocessing gain.
- The adapter uses fixed HTTPS, `xi-api-key` authentication and `mp3_44100_128` output. Redirects
  are disabled so a credential cannot follow an unexpected redirect. No unofficial proxy is used.
- Selecting ElevenLabs sends the rendered script to that vendor and can consume account credits,
  including retried synthesis. Account terms, voice/model access and data retention need assessment
  before enabling it. This implementation does not assume zero-retention access or free usage.

After editing `.env`, rebuild/recreate only the API:

```powershell
docker compose up -d --build --wait tts-service
```

No Meta token change or n8n workflow re-import is required for a speech-provider switch. Test
routing and the actual WhatsApp reply window still apply when sending.

## Validation and test boundaries

Unit tests mock ElevenLabs HTTP responses to check authentication, request shape, voice selection,
prosody, byte limits, deadlines/cancellation, closing responses/sessions, sanitized errors and no
automatic failover. No real ElevenLabs call or account validation is performed without credentials.

To verify both provider paths with actual MP3 decoding and OGG/Opus encoding and no external network:

```powershell
docker run --rm --network none --mount "type=bind,source=${PWD}/tests,target=/srv/tests,readonly" payment-reminder-mvp-tts-service:local python /srv/tests/provider_audio_smoke.py
```

That fixture uses a local tone instead of online speech, the real common service and converter,
and a mocked ElevenLabs HTTP session. It checks codecs/transport, not voice quality. Existing n8n
integration tests continue to verify delivery orchestration independently of the speech engine.

Primary references: [ElevenLabs create-speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert?explorer=true),
[speed control](https://help.elevenlabs.io/hc/en-us/articles/13416271012497-Can-I-slow-down-the-pace-of-the-voice).
