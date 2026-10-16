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
    "first_name": "Alex",
    "agent_name": "Rain from AMG",
    "bank_name": "ABC Bank",
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
            "url": "http://tts-service:8000/api/v1/customers/prepare",
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
        "return {json:{voice_request:{...$json.voice_request,"
        "agent_name:c.voice_request.agent_name,bank_name:c.voice_request.bank_name}}};",
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
            "$('Prepare Voice Request').item.json.voice_request.customer_id + '.mp3' }}",
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
        "next_step:'Play the MP3. Set up Meta test credentials before selecting send mode.'},"
        "binary:$binary };",
        1540,
        -300,
    )
    config = "$('Validate Demo Setup').first().json"
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
            "content": "## WhatsApp Voice Test\n\nDefault: **CSV + preview**. "
            "Each eligible CSV row gets a recording. All sends use the verified test phone.\n\n"
            "For live testing, follow **docs/whatsapp-test.md**. "
            "Use Meta's supplied test sender and your own verified recipient. "
            "Send Hello first, then enter its UTC time in Demo Settings.\n\n"
            "Select the same Header Auth credential on Upload and Send: "
            "`Authorization: Bearer <token>`. Never paste the token into Demo Settings.\n\n"
            "Edit agent and bank in Demo Settings. CSV supplies customer names and dates. "
            "Set input_mode=single for Alex only.\n\n"
            "Manual test only. Duplicate CSV IDs/due dates are skipped within each batch. "
            "Every send-mode run is a fresh batch; don't rerun unknown results blindly.",
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
        ("Prepare Voice Request", "Generate Demo MP3"),
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
    connect("Use CSV Customers", "Read WhatsApp customers.csv", 0)
    connect("Use CSV Customers", "Each WhatsApp Customer", 1)
    connect("Each WhatsApp Customer", "Batch Complete", 0)
    connect("Each WhatsApp Customer", "Customer Eligible", 1)
    connect("Customer Eligible", "Prepare Voice Request", 0)
    connect("Customer Eligible", "Customer Skipped", 1)
    connect("Customer Skipped", "Each WhatsApp Customer")
    connect("Record Customer Outcome", "Each WhatsApp Customer")
    for terminal in ("Preview Complete", "TTS Failed", "Upload Failed", "WhatsApp Result"):
        connect(terminal, "Record Customer Outcome")
    shifted = {
        "Generate Demo MP3",
        "MP3 Ready",
        "TTS Failed",
        "Preview Only",
        "Save WhatsApp Preview",
        "Preview Complete",
        "Upload MP3 to Meta",
        "Upload Accepted",
        "Upload Failed",
        "Check Window and Prepare Audio",
        "Send WhatsApp Audio",
        "WhatsApp Result",
    }
    for item in nodes:
        if item["name"] in shifted:
            item["position"][0] += 1980
            item["position"][1] -= 100
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
