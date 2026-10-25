import asyncio

import pytest

from app.services.audio import (
    AudioConversionBusy,
    AudioConversionFailure,
    AudioConversionTimeout,
    AudioConversionUnavailable,
    AudioConverter,
)

OGG = b"OggS" + b"\0" * 24 + b"OpusHead" + b"test-frame"


class Writer:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data = data

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True


class Process:
    def __init__(self, output=OGG, code=0, hang=False):
        self.stdin = Writer()
        self.stdout = self
        self.output = output
        self.returncode = None if hang else code
        self.hang = hang
        self.killed = False

    async def read(self, size):
        if self.hang:
            await asyncio.sleep(10)
        chunk, self.output = self.output[:size], self.output[size:]
        return chunk

    async def wait(self):
        while self.returncode is None:
            await asyncio.sleep(0.001)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def setup_process(monkeypatch, process):
    calls = []

    async def create(*args, **kwargs):
        calls.append(args)
        return process

    monkeypatch.setattr("app.services.audio.asyncio.create_subprocess_exec", create)
    return calls


def test_opus_conversion_contract_and_cleanup(settings, monkeypatch):
    process = Process()
    calls = setup_process(monkeypatch, process)
    converter = AudioConverter(settings)
    assert asyncio.run(converter.to_opus(b"ID3-test")) == OGG
    assert process.stdin.data == b"ID3-test" and process.stdin.closed
    command = calls[0]
    assert command[command.index("-c:a") + 1] == "libopus"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-protocol_whitelist") + 1] == "pipe"
    assert converter.semaphore._value == settings.max_concurrency


@pytest.mark.parametrize("data,code", [(b"", 0), (b"OggS-not-opus", 0), (OGG, 1)])
def test_invalid_converter_output_is_rejected(settings, monkeypatch, data, code):
    setup_process(monkeypatch, Process(data, code))
    converter = AudioConverter(settings)
    with pytest.raises(AudioConversionFailure):
        asyncio.run(converter.to_opus(b"ID3-test"))
    assert converter.semaphore._value == settings.max_concurrency


def test_converter_timeout_kills_child_and_releases_capacity(settings, monkeypatch):
    settings.audio_conversion_timeout_seconds = 0.01
    process = Process(hang=True)
    setup_process(monkeypatch, process)
    converter = AudioConverter(settings)
    with pytest.raises(AudioConversionTimeout):
        asyncio.run(converter.to_opus(b"ID3-test"))
    assert process.killed
    assert converter.semaphore._value == settings.max_concurrency


def test_converter_missing_binary(settings, monkeypatch):
    async def absent(*args, **kwargs):
        raise FileNotFoundError("private system path")

    monkeypatch.setattr("app.services.audio.asyncio.create_subprocess_exec", absent)
    converter = AudioConverter(settings)
    with pytest.raises(AudioConversionUnavailable):
        asyncio.run(converter.to_opus(b"ID3-test"))
    assert converter.semaphore._value == settings.max_concurrency


def test_converter_size_bounds(settings, monkeypatch):
    settings.max_audio_bytes = 1024
    converter = AudioConverter(settings)
    calls = setup_process(monkeypatch, Process(b"x" * 1025))
    with pytest.raises(AudioConversionFailure):
        asyncio.run(converter.to_opus(b"x" * 1025))
    assert not calls
    with pytest.raises(AudioConversionFailure):
        asyncio.run(converter.to_opus(b"ID3-test"))
    assert converter.semaphore._value == settings.max_concurrency


def test_converter_concurrency_limit(settings):
    converter = AudioConverter(settings)

    async def busy():
        for _ in range(settings.max_concurrency):
            await converter.semaphore.acquire()
        with pytest.raises(AudioConversionBusy):
            await converter.to_opus(b"ID3-test")

    asyncio.run(busy())
