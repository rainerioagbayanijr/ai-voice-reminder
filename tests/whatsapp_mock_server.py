"""Local transport fixture: never connects to Meta or any external recipient."""

import base64
import json
import sys
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/srv")
from app.services.customers import prepare_customer_batch  # noqa: E402

state = {"mode": "accept", "tts_calls": 0, "tts_requests": [], "uploads": [], "messages": []}
AUDIO = b"ID3-whatsapp-transport-fixture"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond(200, state)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/reset":
            state.update(
                mode=json.loads(body)["mode"], tts_calls=0, tts_requests=[], uploads=[], messages=[]
            )
            return self.respond(200, {"ok": True})
        if self.path == "/customers/prepare":
            return self.respond(
                200, {"customers": prepare_customer_batch(json.loads(body)["rows"])}
            )
        if self.path == "/tts":
            state["tts_calls"] += 1
            if state["mode"] == "tts_fail":
                return self.respond(502, {"detail": "Test provider failure"})
            state["tts_requests"].append(json.loads(body))
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Disposition", 'attachment; filename="payment_reminder.mp3"')
            self.send_header("Content-Length", str(len(AUDIO)))
            self.end_headers()
            self.wfile.write(AUDIO)
            return
        if self.headers.get("Authorization") != "Bearer local-whatsapp-test-only":
            return self.respond(401, {"error": {"message": "Test token rejected"}})
        if self.path.endswith("/media"):
            if state["mode"] == "upload_fail":
                return self.respond(403, {"error": {"message": "Test upload rejected"}})
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
            )
            fields = {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                data = part.get_payload(decode=True)
                fields[name] = base64.b64encode(data).decode() if name == "file" else data.decode()
                if name == "file":
                    fields["filename"] = part.get_filename()
                    fields["mime_type"] = part.get_content_type()
            state["uploads"].append(fields)
            return self.respond(200, {"id": "123456789"})
        if self.path.endswith("/messages"):
            payload = json.loads(body)
            if state["mode"] == "send_fail":
                return self.respond(500, {"error": {"message": "Test send failure"}})
            state["messages"].append(payload)
            if state["mode"] == "disconnect":
                self.close_connection = True
                return  # Captured submission with no acknowledgement.
            return self.respond(
                200, {"messaging_product": "whatsapp", "messages": [{"id": "wamid.local-test"}]}
            )
        self.respond(404, {"error": "Unknown test endpoint"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
