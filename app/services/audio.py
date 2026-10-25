"""Bounded, in-memory MP3 -> OGG/Opus conversion for WhatsApp voice notes."""

import asyncio

from app.core.config import Settings


class AudioConversionFailure(Exception):
    pass


class AudioConversionUnavailable(Exception):
    pass


class AudioConversionTimeout(Exception):
    pass


class AudioConversionBusy(Exception):
    pass


class AudioConverter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def to_opus(self, mp3: bytes) -> bytes:
        if not mp3 or len(mp3) > self.settings.max_audio_bytes:
            raise AudioConversionFailure
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.1)
        except TimeoutError:
            raise AudioConversionBusy from None
        process = None
        tasks = []
        try:
            async with asyncio.timeout(self.settings.audio_conversion_timeout_seconds):
                try:
                    process = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-protocol_whitelist",
                        "pipe",
                        "-f",
                        "mp3",
                        "-i",
                        "pipe:0",
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-sn",
                        "-dn",
                        "-map_metadata",
                        "-1",
                        "-c:a",
                        "libopus",
                        "-application",
                        "voip",
                        "-b:a",
                        "32k",
                        "-ac",
                        "1",
                        "-ar",
                        "48000",
                        "-f",
                        "ogg",
                        "pipe:1",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                except OSError:
                    raise AudioConversionUnavailable from None

                async def feed():
                    try:
                        process.stdin.write(mp3)
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # The exit code/output determines whether decoding succeeded.
                    finally:
                        process.stdin.close()

                async def collect():
                    data = bytearray()
                    while chunk := await process.stdout.read(65536):
                        data.extend(chunk)
                        if len(data) > self.settings.max_audio_bytes:
                            raise AudioConversionFailure
                    return bytes(data)

                tasks = [
                    asyncio.create_task(feed()),
                    asyncio.create_task(collect()),
                    asyncio.create_task(process.wait()),
                ]
                _, audio, code = await asyncio.gather(*tasks)
                if code != 0 or not audio.startswith(b"OggS") or b"OpusHead" not in audio[:128]:
                    raise AudioConversionFailure
                return audio
        except TimeoutError:
            raise AudioConversionTimeout from None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if process is not None:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await process.wait()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.semaphore.release()
