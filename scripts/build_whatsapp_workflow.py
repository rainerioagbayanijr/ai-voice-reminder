"""Build an independent, manually triggered Meta Cloud API audio test workflow.

Uses pinned n8n HTTP Request 4.2 / Set 3.4 parameters. No tokens are embedded.
The Meta version is copied from the operator's dashboard, not guessed here.
"""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "input_mode": "csv",
    "mode": "preview",
    "routing_mode": "test",
    "window_source": "manual",
    "institution_id": "demo-bank",
    "first_name": "Alex",
    "agent_name": "Rain from Test Company",
    "bank_name": "Test Bank",
    "due_date": "2026-11-15",
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
    condition("Use CSV Customers", "={{ $json.input_mode === 'csv' }}", 660, 0)
    node(
        "Read WhatsApp customers.csv",
        "readWriteFile",
        1.1,
        {
            "operation": "read",
            "fileSelector": "/files/input/customers.csv",
            "options": {},
        },
        880,
        -220,
    )
    node(
        "Parse WhatsApp CSV",
        "extractFromFile",
        1.1,
        {
            "operation": "csv",
            "binaryPropertyName": "data",
            "options": {"headerRow": True},
        },
        1100,
        -220,
    )
    node(
        "Collect CSV Rows",
        "code",
        2,
        {
            "mode": "runOnceForAllItems",
            "jsCode": "return [{json:{rows:$input.all().map(item=>item.json)}}];",
        },
        1320,
        -220,
    )
    node(
        "Validate CSV Batch",
        "httpRequest",
        4.2,
        {
            "method": "POST",
            "url": "http://tts-service:8000/api/v1/whatsapp/customers/prepare",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "X-API-Key", "value": "={{ $env.REMINDER_API_KEY }}"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ $json }}",
            "options": {"timeout": 30000},
        },
        1540,
        -220,
        retryOnFail=True,
        maxTries=3,
        waitBetweenTries=3000,
    )
    node(
        "Expand Prepared Customers",
        "code",
        2,
        {
            "mode": "runOnceForAllItems",
            "jsCode": "return $input.first().json.customers.map("
            "json=>({json,pairedItem:{item:0}}));",
        },
        1760,
        -220,
    )
    node("Each WhatsApp Customer", "splitInBatches", 3, {"batchSize": 1, "options": {}}, 1980, 0)
    condition("Customer Eligible", "={{ $json.status === 'eligible' }}", 2200, 0)
    result("Customer Skipped", "return {json:{channel:'whatsapp',...$json}};", 2420, 240)
    result(
        "Prepare Voice Request",
        "const c=$('Validate Demo Setup').first().json;"
        "const voice={...$json.voice_request,agent_name:c.voice_request.agent_name,"
        "bank_name:c.voice_request.bank_name};"
        "return {json:{voice_request:voice,row:{...($json.row||{}),...voice,"
        "reminder_eligible:true}}};",
        2420,
        -100,
    )
    result(
        "Record Customer Outcome",
        "const v=$('Prepare Voice Request').item.json.voice_request;"
        "return {json:{...$json,customer_id:v.customer_id,first_name:v.first_name,"
        "due_date:v.due_date}};",
        4840,
        420,
    )
    node(
        "Batch Complete",
        "code",
        2,
        {
            "mode": "runOnceForAllItems",
            "jsCode": "const results=$input.all().map(item=>item.json);const counts={};"
            "for(const r of results)counts[r.status]=(counts[r.status]||0)+1;"
            "return [{json:{channel:'whatsapp',status:results.length===1?results[0].status:"
            "'batch_complete',total:results.length,counts,results}}];",
        },
        2200,
        480,
    )
    node(
        "Generate Voice Note",
        "httpRequest",
        4.2,
        {
            "method": "POST",
            "url": "http://tts-service:8000/api/v1/voice/generate?audio_format=ogg_opus",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [{"name": "X-API-Key", "value": "={{ $env.REMINDER_API_KEY }}"}]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ $json.voice_request }}",
            "options": {
                "timeout": 70000,
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
    condition("Voice Note Ready", "={{ !!$binary?.audio && !$json.error }}", 880, 0)
    result(
        "TTS Failed",
        "return { json: {channel:'whatsapp',status:'failed',stage:'tts',"
        "send_attempted:false,next_step:'Inspect Generate Voice Note. "
        "No WhatsApp message was attempted.'} };",
        1100,
        280,
    )
    condition(
        "Preview Only",
        "={{ $('Validate Demo Setup').first().json.mode === 'preview' }}",
        1100,
        -100,
    )
    node(
        "Save WhatsApp Preview",
        "readWriteFile",
        1.1,
        {
            "operation": "write",
            "fileName": "={{ '/files/previews/whatsapp-' + $execution.id + '-' + "
            "$('Prepare Voice Request').item.json.voice_request.customer_id + '.ogg' }}",
            "dataPropertyName": "audio",
            "options": {},
        },
        1320,
        -300,
    )
    result(
        "Preview Complete",
        "return { json: {channel:'whatsapp',status:'preview',"
        "file:$json.fileName,"
        "customer_id:$('Prepare Voice Request').item.json.voice_request.customer_id,"
        "first_name:$('Prepare Voice Request').item.json.voice_request.first_name,"
        "send_attempted:false,"
        "next_step:'Play the voice-note preview. "
        "Set up Meta test credentials before selecting send mode.'},"
        "binary:$binary };",
        1540,
        -300,
    )
    config = "$('Validate Demo Setup').first().json"
    url = "={{ 'https://graph.facebook.com/' + " + config + ".graph_api_version + '/' + "
    url += config + ".phone_number_id + '/"
    auth = {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"}
    node(
        "Upload Voice Note to Meta",
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
                    {"name": "type", "value": "audio/ogg"},
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
        "send_attempted:false,next_step:'Inspect Upload Voice Note to Meta and check the "
        "token, API version and Phone Number ID.'} };",
        1760,
        240,
    )
    # A backend reservation issues a send payload once, checking ownership, recipient and window.
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
            "jsonBody": "={{ $json.payload }}",
            "options": {
                "timeout": 30000,
                "response": {
                    "response": {
                        "fullResponse": True,
                        "neverError": True,
                        "responseFormat": "json",
                    }
                },
            },
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
            "content": "## WhatsApp reminders\n\nDefault: **CSV + preview + test routing**. "
            "Send mode uses a durable PostgreSQL claim and single-use reservation.\n\n"
            "For live testing, follow **docs/whatsapp-test.md**. "
            "Use Meta's supplied test sender and your own verified recipient. "
            "Send Hello first. With window_source=webhook and backend "
            "WHATSAPP_WINDOW_SOURCE=webhook, its timestamp is recorded automatically. "
            "Manual mode still requires last_hello_at_utc.\n\n"
            "Select the same Header Auth credential on Upload and Send: "
            "`Authorization: Bearer <token>`. Never paste the token into Demo Settings.\n\n"
            "Edit agent and bank in Demo Settings. CSV supplies customer names and dates. "
            "Set input_mode=single for Alex only.\n\n"
            "Keep institution_id stable. Submitted/unknown/submitting/rejected reminders "
            "are never automatically resent. Safe preparation failures retry on a later run, "
            "subject to backend delay/attempt limits.\n\n"
            "Customer routing requires CSV numbers, a recent incoming message per recipient "
            "and backend "
            "WHATSAPP_CUSTOMER_ROUTING_ENABLED=true. Never use fictional CSV phones for sending.",
            "width": 660,
            "height": 380,
        },
        0,
        -480,
    )
    for source, target in [
        ("Start WhatsApp Test", "Demo Settings"),
        ("Demo Settings", "Validate Demo Setup"),
        ("Validate Demo Setup", "Use CSV Customers"),
        ("Read WhatsApp customers.csv", "Parse WhatsApp CSV"),
        ("Parse WhatsApp CSV", "Collect CSV Rows"),
        ("Collect CSV Rows", "Validate CSV Batch"),
        ("Validate CSV Batch", "Expand Prepared Customers"),
        ("Expand Prepared Customers", "Each WhatsApp Customer"),
        ("Generate Voice Note", "Voice Note Ready"),
        ("Save WhatsApp Preview", "Preview Complete"),
        ("Upload Voice Note to Meta", "Upload Accepted"),
        ("Send WhatsApp Audio", "WhatsApp Result"),
    ]:
        connect(source, target)
    connect("Voice Note Ready", "Preview Only", 0)
    connect("Voice Note Ready", "TTS Failed", 1)
    connect("Preview Only", "Save WhatsApp Preview", 0)
    connect("Preview Only", "Upload Voice Note to Meta", 1)
    connect("Upload Accepted", "Reserve WhatsApp Send", 0)
    connect("Upload Accepted", "Upload Failed", 1)
    connect("Use CSV Customers", "Read WhatsApp customers.csv", 0)
    connect("Use CSV Customers", "Each WhatsApp Customer", 1)
    connect("Each WhatsApp Customer", "Batch Complete", 0)
    connect("Each WhatsApp Customer", "Customer Eligible", 1)
    connect("Customer Eligible", "Prepare Voice Request", 0)
    connect("Customer Eligible", "Customer Skipped", 1)
    connect("Customer Skipped", "Each WhatsApp Customer")
    connect("Record Customer Outcome", "Each WhatsApp Customer")
    connect("Preview Complete", "Record Customer Outcome")

    # Keep orchestration in n8n; validation, ownership and state transitions are Python/SQL.
    def backend(name, endpoint, body, x, y, *, retry=False):
        node(
            name,
            "httpRequest",
            4.2,
            {
                "method": "POST",
                "url": endpoint,
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {"name": "X-API-Key", "value": "={{ $env.REMINDER_API_KEY }}"},
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": body,
                "options": {"timeout": 15000},
            },
            x,
            y,
            retryOnFail=retry,
            maxTries=3,
            waitBetweenTries=3000,
            onError="continueRegularOutput",
        )

    condition(
        "Track Send Mode",
        "={{ $('Validate Demo Setup').first().json.mode === 'send' }}",
        2500,
        -200,
    )
    backend(
        "Claim WhatsApp Reminder",
        "http://tts-service:8000/api/v1/whatsapp/reminders/claim",
        "={{ {row:$json.row,institution_id:$('Validate Demo Setup').first().json.institution_id,"
        "routing_mode:$('Validate Demo Setup').first().json.routing_mode,"
        "phone_number_id:$('Validate Demo Setup').first().json.phone_number_id,"
        "test_recipient:$('Validate Demo Setup').first().json.test_recipient,"
        "last_hello_at_utc:$('Validate Demo Setup').first().json.last_hello_at_utc} }}",
        2700,
        -300,
    )
    condition("Claim Acquired", "={{ $json.proceed === true && !$json.error }}", 2900, -300)
    result(
        "Claim Skipped",
        "return {json:{channel:'whatsapp',status:$json.error?'tracking_error':'skipped',"
        "reason:$json.error?'claim_unavailable':$json.reason,send_attempted:false}};",
        2900,
        200,
    )
    claim = "$('Claim WhatsApp Reminder').item.json"
    backend(
        "Reserve WhatsApp Send",
        "={{ 'http://tts-service:8000/api/v1/whatsapp/reminders/' + "
        + claim
        + ".reminder_id + '/reserve' }}",
        "={{ {token:" + claim + ".token,recipient:" + claim + ".recipient,media_id:$json.id} }}",
        3900,
        -300,
    )
    condition("Send Reserved", "={{ $json.proceed === true && !$json.error }}", 4100, -300)
    result(
        "Reservation Stopped",
        "return {json:{channel:'whatsapp',status:$json.error?'held_for_review':'failed',"
        "reason:$json.error?'reservation_unconfirmed':$json.reason,send_attempted:false,"
        "automatic_retry:false}};",
        4100,
        220,
    )
    condition(
        "Outcome Needs Tracking",
        "={{ $('Validate Demo Setup').first().json.mode === 'send' }}",
        4500,
        320,
    )
    result(
        "Prepare Tracking Outcome",
        "const status=$json.status;const stage=$json.stage;"
        "return {json:{...$json,tracking:{token:" + claim + ".token,status,"
        "error_code:$json.error_code||(stage==='tts'?'tts_failed':"
        "stage==='upload'?'upload_failed':null),message_id:$json.message_id||null}}};",
        4700,
        220,
    )
    backend(
        "Record WhatsApp Status",
        "={{ 'http://tts-service:8000/api/v1/whatsapp/reminders/' + "
        + claim
        + ".reminder_id + '/outcome' }}",
        "={{ $json.tracking }}",
        4900,
        220,
        retry=True,
    )
    result(
        "Outcome Recorded",
        "const {tracking,...result}=$('Prepare Tracking Outcome').item.json;"
        "return {json:{...result,tracking_recorded:!$json.error,"
        "...($json.error?{status:'held_for_review',reason:'outcome_unconfirmed'}:{})}};",
        5100,
        220,
    )
    connect("Prepare Voice Request", "Track Send Mode")
    connect("Track Send Mode", "Claim WhatsApp Reminder", 0)
    connect("Track Send Mode", "Generate Voice Note", 1)
    connect("Claim WhatsApp Reminder", "Claim Acquired")
    connect("Claim Acquired", "Generate Voice Note", 0)
    connect("Claim Acquired", "Claim Skipped", 1)
    connect("Claim Skipped", "Record Customer Outcome")
    connect("Reserve WhatsApp Send", "Send Reserved")
    connect("Send Reserved", "Send WhatsApp Audio", 0)
    connect("Send Reserved", "Reservation Stopped", 1)
    connect("Reservation Stopped", "Record Customer Outcome")
    for terminal in ("TTS Failed", "Upload Failed", "WhatsApp Result"):
        connect(terminal, "Outcome Needs Tracking")
    connect("Outcome Needs Tracking", "Prepare Tracking Outcome", 0)
    connect("Outcome Needs Tracking", "Record Customer Outcome", 1)
    connect("Prepare Tracking Outcome", "Record WhatsApp Status")
    connect("Record WhatsApp Status", "Outcome Recorded")
    connect("Outcome Recorded", "Record Customer Outcome")
    positions = {
        "Track Send Mode": [2660, -100],
        "Claim WhatsApp Reminder": [2900, -260],
        "Claim Acquired": [3140, -260],
        "Claim Skipped": [3380, 300],
        "Generate Voice Note": [3380, -100],
        "Voice Note Ready": [3620, -100],
        "TTS Failed": [3860, 300],
        "Preview Only": [3860, -100],
        "Save WhatsApp Preview": [4100, -500],
        "Preview Complete": [4340, -500],
        "Upload Voice Note to Meta": [4100, -100],
        "Upload Accepted": [4340, -100],
        "Upload Failed": [4580, 300],
        "Reserve WhatsApp Send": [4580, -100],
        "Send Reserved": [4820, -100],
        "Reservation Stopped": [5060, 300],
        "Send WhatsApp Audio": [5060, -100],
        "WhatsApp Result": [5300, -100],
        "Outcome Needs Tracking": [5540, 100],
        "Prepare Tracking Outcome": [5780, 100],
        "Record WhatsApp Status": [6020, 100],
        "Outcome Recorded": [6260, 100],
        "Record Customer Outcome": [6500, 100],
    }
    for item in nodes:
        if item["name"] in positions:
            item["position"] = positions[item["name"]]
    return {
        "id": "whatsappVoiceTestMvp",
        "name": "WhatsApp Voice Reminder - Test Only",
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": "Asia/Singapore", "executionTimeout": 600},
        "pinData": {},
        "tags": [],
        "versionId": str(uuid5(NAMESPACE_URL, "whatsapp-voice-test-v4-webhooks")),
    }


if __name__ == "__main__":
    path = ROOT / "workflows/whatsapp_voice_test.json"
    path.write_text(json.dumps(build_workflow(), indent=2) + "\n", encoding="utf-8")
    print(path)
