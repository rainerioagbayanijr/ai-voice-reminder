"""Build an independent, manually triggered Meta Cloud API audio test workflow.

Uses pinned n8n HTTP Request 4.2 / Set 3.4 parameters. No tokens are embedded.
The Meta version is copied from the operator's dashboard, not guessed here.
"""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "mode": "preview",
    "first_name": "Alex",
    "test_recipient": "",
    "phone_number_id": "",
    "graph_api_version": "",
    "last_hello_at_utc": "",
    "meta_test_number_confirmed": False,
    "recipient_verified": False,
}


def build_workflow() -> dict:
    nodes = []
    connections = {}

    def node(name, kind, version, parameters, x, y, **extra):
        nodes.append(
            {
                "id": str(uuid5(NAMESPACE_URL, "whatsapp-demo/" + name)),
                "name": name,
                "type": "n8n-nodes-base." + kind,
                "typeVersion": version,
                "position": [x, y],
                "parameters": parameters,
                **extra,
            }
        )

    def connect(source, target, output=0):
        branches = connections.setdefault(source, {"main": []})["main"]
        while len(branches) <= output:
            branches.append([])
        branches[output].append({"node": target, "type": "main", "index": 0})

    def condition(name, expression, x, y):
        node(
            name,
            "if",
            2.2,
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": str(uuid5(NAMESPACE_URL, "whatsapp-demo/" + name)),
                            "leftValue": expression,
                            "rightValue": True,
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            x,
            y,
        )

    def code(name, filename, x, y):
        source = (ROOT / "workflows/code" / filename).read_text(encoding="utf-8")
        node(name, "code", 2, {"mode": "runOnceForEachItem", "jsCode": source}, x, y)

    def result(name, source, x, y):
        node(name, "code", 2, {"mode": "runOnceForEachItem", "jsCode": source}, x, y)

    node("Start WhatsApp Test", "manualTrigger", 1, {}, 0, 0)
    node(
        "Demo Settings",
        "set",
        3.4,
        {"mode": "raw", "jsonOutput": json.dumps(CONFIG, indent=2), "options": {}},
        220,
        0,
    )
    code("Validate Demo Setup", "whatsapp_validate.js", 440, 0)
    node(
        "Generate Demo MP3",
        "httpRequest",
        4.2,
        {
            "method": "POST",
            "url": "http://tts-service:8000/api/v1/voice/generate",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [{"name": "X-API-Key", "value": "={{ $env.REMINDER_API_KEY }}"}]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ $json.voice_request }}",
            "options": {
                "timeout": 55000,
                "response": {"response": {"responseFormat": "file", "outputPropertyName": "audio"}},
            },
        },
        660,
        0,
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=5000,
        onError="continueRegularOutput",
    )
    condition("MP3 Ready", "={{ !!$binary?.audio && !$json.error }}", 880, 0)
    result(
        "TTS Failed",
        "return { json: {channel:'whatsapp',status:'failed',stage:'tts',"
        "send_attempted:false,next_step:'Inspect Generate Demo MP3. "
        "No WhatsApp message was attempted.'} };",
        1100,
        280,
    )
    condition(
        "Preview Only", "={{ $('Validate Demo Setup').item.json.mode === 'preview' }}", 1100, -100
    )
    node(
        "Save WhatsApp Preview",
        "readWriteFile",
        1.1,
        {
            "operation": "write",
            "fileName": "={{ '/files/previews/whatsapp-' + $execution.id + '.mp3' }}",
            "dataPropertyName": "audio",
            "options": {},
        },
        1320,
        -300,
    )
    result(
        "Preview Complete",
        "return { json: {channel:'whatsapp',status:'preview',"
        "file:$json.fileName,send_attempted:false,"
        "next_step:'Play the MP3. Set up Meta test credentials before selecting send mode.'},"
        "binary:$binary };",
        1540,
        -300,
    )
    config = "$('Validate Demo Setup').item.json"
    url = "={{ 'https://graph.facebook.com/' + " + config + ".graph_api_version + '/' + "
    url += config + ".phone_number_id + '/"
    auth = {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"}
    node(
        "Upload MP3 to Meta",
        "httpRequest",
        4.2,
        {
            **auth,
            "method": "POST",
            "url": url + "media' }}",
            "sendBody": True,
            "contentType": "multipart-form-data",
            "bodyParameters": {
                "parameters": [
                    {"name": "messaging_product", "value": "whatsapp"},
                    {"name": "type", "value": "audio/mpeg"},
                    {
                        "parameterType": "formBinaryData",
                        "name": "file",
                        "inputDataFieldName": "audio",
                    },
                ]
            },
            "options": {"timeout": 30000},
        },
        1320,
        0,
        retryOnFail=True,
        maxTries=2,
        waitBetweenTries=3000,
        onError="continueRegularOutput",
    )
    condition(
        "Upload Accepted",
        "={{ !$json.error && typeof $json.id === 'string' && /^[0-9]{1,64}$/.test($json.id) }}",
        1540,
        0,
    )
    result(
        "Upload Failed",
        "return { json: {channel:'whatsapp',status:'failed',stage:'upload',"
        "send_attempted:false,next_step:'Inspect Upload MP3 to Meta and check the "
        "token, API version and Phone Number ID.'} };",
        1760,
        240,
    )
    code("Check Window and Prepare Audio", "whatsapp_before_send.js", 1760, -100)
    node(
        "Send WhatsApp Audio",
        "httpRequest",
        4.2,
        {
            **auth,
            "method": "POST",
            "url": url + "messages' }}",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ $json }}",
            "options": {"timeout": 30000},
        },
        1980,
        -100,
        retryOnFail=False,
        onError="continueRegularOutput",
    )
    code("WhatsApp Result", "whatsapp_result.js", 2200, -100)
    node(
        "Read Me - Test Setup",
        "stickyNote",
        1,
        {
            "content": "## WhatsApp Voice Test\n\nDefault: **preview**. Run now to save an MP3.\n\n"
            "For live testing, follow **docs/whatsapp-test.md**. "
            "Use Meta's supplied test sender and your own verified recipient. "
            "Send Hello first, then enter its UTC time in Demo Settings.\n\n"
            "Select the same Header Auth credential on Upload and Send: "
            "`Authorization: Bearer <token>`. Never paste the token into Demo Settings.\n\n"
            "Manual test only. No automatic inbound trigger, schedule, paid provider, "
            "or customer CSV. `submitted` means API accepted, not delivered. "
            "Each send-mode run is a new attempt; don't rerun an unknown result blindly.",
            "width": 660,
            "height": 380,
        },
        0,
        -480,
    )
    for source, target in [
        ("Start WhatsApp Test", "Demo Settings"),
        ("Demo Settings", "Validate Demo Setup"),
        ("Validate Demo Setup", "Generate Demo MP3"),
        ("Generate Demo MP3", "MP3 Ready"),
        ("Save WhatsApp Preview", "Preview Complete"),
        ("Upload MP3 to Meta", "Upload Accepted"),
        ("Check Window and Prepare Audio", "Send WhatsApp Audio"),
        ("Send WhatsApp Audio", "WhatsApp Result"),
    ]:
        connect(source, target)
    connect("MP3 Ready", "Preview Only", 0)
    connect("MP3 Ready", "TTS Failed", 1)
    connect("Preview Only", "Save WhatsApp Preview", 0)
    connect("Preview Only", "Upload MP3 to Meta", 1)
    connect("Upload Accepted", "Check Window and Prepare Audio", 0)
    connect("Upload Accepted", "Upload Failed", 1)
    return {
        "id": "whatsappVoiceTestMvp",
        "name": "WhatsApp Voice Reminder - Test Only",
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": "Asia/Singapore", "executionTimeout": 600},
        "pinData": {},
        "tags": [],
        "versionId": str(uuid5(NAMESPACE_URL, "whatsapp-voice-test-v1")),
    }


if __name__ == "__main__":
    path = ROOT / "workflows/whatsapp_voice_test.json"
    path.write_text(json.dumps(build_workflow(), indent=2) + "\n", encoding="utf-8")
    print(path)
