"""Reproducible export using node definitions from n8n@2.43.6. No credentials."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
nodes = []
connections = {}


def node(name, kind, version, parameters, x, y, **extra):
    nodes.append(
        {
            "id": str(uuid5(NAMESPACE_URL, name)),
            "name": name,
            "type": "n8n-nodes-base." + kind,
            "typeVersion": version,
            "position": [x, y],
            "parameters": parameters,
            **extra,
        }
    )


def connect(source, target, output=0):
    outputs = connections.setdefault(source, {"main": []})["main"]
    while len(outputs) <= output:
        outputs.append([])
    outputs[output].append({"node": target, "type": "main", "index": 0})


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
                        "id": str(uuid5(NAMESPACE_URL, name + "condition")),
                        "leftValue": expression,
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
        x,
        y,
    )


def http(name, path, body, x, y, *, retry=False, continue_error=False, audio=False):
    options = {"timeout": 55000 if audio else 15000}
    if audio:
        options["response"] = {
            "response": {"responseFormat": "file", "outputPropertyName": "audio"}
        }
    node(
        name,
        "httpRequest",
        4.2,
        {
            "method": "POST",
            "url": path,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [{"name": "X-API-Key", "value": "={{ $env.REMINDER_API_KEY }}"}]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
            "options": options,
        },
        x,
        y,
        retryOnFail=retry,
        maxTries=3,
        waitBetweenTries=5000,
        onError="continueRegularOutput" if continue_error else "stopWorkflow",
    )


base = "http://tts-service:8000/api/v1"
claim = "$('Validate and Claim').item.json"
status_url = "={{ '" + base + "/reminders/' + " + claim + ".reminder_id + '/status' }}"


def status(name, value, x, y, error=None, retry=True):
    fields = f"token: {claim}.token, status: '{value}'"
    if error:
        fields += f", error_code: '{error}'"
    http(name, status_url, "={{ { " + fields + " } }}", x, y, retry=retry)


node("Manual Trigger", "manualTrigger", 1, {}, 0, 0)
node(
    "Daily at 09 Manila",
    "scheduleTrigger",
    1.2,
    {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
    0,
    180,
)
node(
    "Read customers.csv",
    "readWriteFile",
    1.1,
    {"operation": "read", "fileSelector": "/files/input/customers.csv", "options": {}},
    220,
    0,
)
node(
    "Parse CSV",
    "extractFromFile",
    1.1,
    {"operation": "csv", "binaryPropertyName": "data", "options": {"headerRow": True}},
    440,
    0,
)
node("Each Customer", "splitInBatches", 3, {"batchSize": 1, "options": {}}, 660, 0)
http("Validate and Claim", base + "/reminders/claim", "={{ { row: $json } }}", 880, 100)
condition("Eligible and Claimed", "={{ $json.proceed === true }}", 1100, 100)
http(
    "Generate Audio",
    base + "/voice/generate",
    "={{ $json.voice_request }}",
    1320,
    0,
    retry=True,
    continue_error=True,
    audio=True,
)
condition("Audio Generated", "={{ !!$binary?.audio && !$json.error }}", 1540, 0)
status("Record TTS Failure", "failed", 1760, 320, "tts_failed")
condition("Dry Run", "={{ " + claim + ".dry_run === true }}", 1760, -100)
node(
    "Save MP3 Preview",
    "readWriteFile",
    1.1,
    {
        "operation": "write",
        "fileName": "={{ '/files/previews/' + " + claim + ".reminder_id + '.mp3' }}",
        "dataPropertyName": "audio",
        "options": {},
    },
    1980,
    -300,
    onError="continueRegularOutput",
)
condition("Preview Saved", "={{ !$json.error }}", 2200, -300)
status("Record Dry Run", "dry_run", 2420, -400)
status("Record Preview Failure", "failed", 2420, -200, "preview_failed")
status("Reserve SMTP Submission", "submitting", 1980, 0, retry=False)
node(
    "Restore Audio",
    "code",
    2,
    {
        "mode": "runOnceForEachItem",
        "jsCode": "return { json: $('Validate and Claim').item.json, "
        "binary: $('Generate Audio').item.binary };",
    },
    2200,
    0,
)
node(
    "Send Test Email",
    "emailSend",
    2.1,
    {
        "resource": "email",
        "operation": "send",
        "fromEmail": "={{ $json.sender }}",
        "toEmail": "={{ $json.recipient }}",
        "subject": "={{ $json.subject }}",
        "emailFormat": "text",
        "text": "={{ $json.body }}",
        "options": {"fileAttachments": "audio", "appendAttribution": False},
    },
    2420,
    0,
    onError="continueRegularOutput",
    retryOnFail=False,
)
condition(
    "SMTP Accepted",
    "={{ !$json.error && Array.isArray($json.accepted) && "
    "$json.accepted.includes(" + claim + ".recipient) }}",
    2640,
    0,
)
status("Record Sent", "sent", 2860, -100)
status("Record SMTP Uncertain", "unknown", 2860, 140, "smtp_uncertain")
node("Complete", "noOp", 1, {}, 880, -180)

for source, target in [
    ("Manual Trigger", "Read customers.csv"),
    ("Daily at 09 Manila", "Read customers.csv"),
    ("Read customers.csv", "Parse CSV"),
    ("Parse CSV", "Each Customer"),
    ("Validate and Claim", "Eligible and Claimed"),
    ("Generate Audio", "Audio Generated"),
    ("Save MP3 Preview", "Preview Saved"),
    ("Reserve SMTP Submission", "Restore Audio"),
    ("Restore Audio", "Send Test Email"),
    ("Send Test Email", "SMTP Accepted"),
]:
    connect(source, target)
connect("Each Customer", "Complete", 0)
connect("Each Customer", "Validate and Claim", 1)
connect("Eligible and Claimed", "Generate Audio", 0)
connect("Eligible and Claimed", "Each Customer", 1)
connect("Audio Generated", "Dry Run", 0)
connect("Audio Generated", "Record TTS Failure", 1)
connect("Dry Run", "Save MP3 Preview", 0)
connect("Dry Run", "Reserve SMTP Submission", 1)
connect("Preview Saved", "Record Dry Run", 0)
connect("Preview Saved", "Record Preview Failure", 1)
connect("SMTP Accepted", "Record Sent", 0)
connect("SMTP Accepted", "Record SMTP Uncertain", 1)
for name in [
    "Record TTS Failure",
    "Record Dry Run",
    "Record Preview Failure",
    "Record Sent",
    "Record SMTP Uncertain",
]:
    connect(name, "Each Customer")

workflow = {
    "id": "voiceReminderMvp",
    "name": "Fictional Voice Payment Reminders",
    "active": False,
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "timezone": "Asia/Manila", "executionTimeout": 3600},
    "pinData": {},
    "versionId": str(uuid5(NAMESPACE_URL, "voice-reminder-mvp-v1")),
    "tags": [],
}
if __name__ == "__main__":
    path = ROOT / "workflows" / "payment_reminder.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
    print(path)
