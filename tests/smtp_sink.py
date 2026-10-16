"""Local-only SMTP capture for integration tests. Never relays messages."""

import base64
import json
import socketserver
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

messages = []
mode = "accept"
lock = threading.Lock()


class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 local-test-sink ESMTP\r\n")
        while line := self.rfile.readline(10000):
            command = line.decode(errors="replace").strip().upper()
            if command.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250 local-test-sink\r\n")
            elif command.startswith("RCPT") and mode == "reject":
                self.wfile.write(b"550 Test rejection\r\n")
            elif command == "DATA":
                self.wfile.write(b"354 End with dot\r\n")
                data = bytearray()
                while (part := self.rfile.readline(10000)) not in {b".\r\n", b""}:
                    data.extend(part[1:] if part.startswith(b"..") else part)
                message = BytesParser(policy=policy.default).parsebytes(bytes(data))
                with lock:
                    messages.append(
                        {
                            "to": str(message["To"]),
                            "subject": str(message["Subject"]),
                            "attachments": [
                                {
                                    "filename": p.get_filename(),
                                    "data": base64.b64encode(p.get_payload(decode=True)).decode(),
                                }
                                for p in message.iter_attachments()
                            ],
                        }
                    )
                if mode == "disconnect":
                    return  # Simulate accepted DATA with a lost acknowledgement.
                self.wfile.write(b"250 Queued locally\r\n")
            elif command == "QUIT":
                self.wfile.write(b"221 Bye\r\n")
                return
            else:
                self.wfile.write(b"250 OK\r\n")


class HTTP(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps(messages).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global mode
        selected = self.path.strip("/")
        if selected in {"accept", "reject", "disconnect"}:
            mode = selected
        elif selected == "reset":
            with lock:
                messages.clear()
            mode = "accept"
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    server = socketserver.ThreadingTCPServer(("0.0.0.0", 1025), SMTP)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8025), HTTP).serve_forever()
