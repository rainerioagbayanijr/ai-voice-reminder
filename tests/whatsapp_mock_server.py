"""Local transport fixture: never connects to Meta or any external recipient."""

import base64
import json
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/srv")
from app.services.whatsapp import prepare_whatsapp_batch  # noqa: E402

state = {"mode": "accept", "tts_calls": 0, "tts_requests": [], "uploads": [], "messages": []}
# Real, short tone: allows the actual FFmpeg converter to run without online TTS.
AUDIO = subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=0.25",
        "-c:a",
        "libmp3lame",
        "-f",
        "mp3",
        "pipe:1",
    ],
    check=True,
    capture_output=True,
).stdout


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
                200, {"customers": prepare_whatsapp_batch(json.loads(body)["rows"])}
            )
        if self.path == "/tts":
            state["tts_calls"] += 1
            if state["mode"] == "tts_fail":
                return self.respond(502, {"detail": "Test provider failure"})
            state["tts_requests"].append(json.loads(body))
            audio = b"invalid-mp3" if state["mode"] == "conversion_fail" else AUDIO
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Disposition", 'attachment; filename="payment_reminder.mp3"')
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
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
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    "-i",
                    "pipe:0",
                ],
                input=base64.b64decode(fields["file"]),
                capture_output=True,
                check=True,
            )
            fields["audio_stream"] = json.loads(probe.stdout)["streams"][0]
            return self.respond(200, {"id": "123456789"})
        if self.path.endswith("/messages"):
            payload = json.loads(body)
            if state["mode"] == "rate_limit":
                return self.respond(429, {"error": {"code": 130429, "message": "Test throttle"}})
            if state["mode"] == "send_reject":
                return self.respond(400, {"error": {"code": 131026, "message": "Test rejection"}})
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
