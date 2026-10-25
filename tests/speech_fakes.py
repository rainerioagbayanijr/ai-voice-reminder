"""No-network HTTP fixture shared by provider contract and container audio tests."""

import asyncio


class SpeechResponse:
    def __init__(self, chunks=None, *, status=200, content_type="audio/mpeg", delay=0, error=None):
        self.chunks = [b"ID3-test-mp3"] if chunks is None else chunks
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.content = self
        self.delay = delay
        self.error = error
        self.closed = False
        self.read_started = False

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def iter_chunked(self, size):
        self.read_started = True
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk


class SpeechSession:
    def __init__(self, response=None):
        self.response = response or SpeechResponse()
        self.calls = []
        self.options = []
        self.closed = False

    def factory(self, **kwargs):
        self.options.append(kwargs)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response
