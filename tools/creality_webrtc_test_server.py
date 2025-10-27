#!/usr/bin/env python3
"""
A minimal local WebRTC signaling and media server that emulates Creality's WebRTC format.

It exposes:
- POST /call/webrtc_local: Accepts base64(JSON{"type":"offer","sdp":"..."}) and returns
  base64(JSON{"type":"answer","sdp":"..."}). Uses aiortc to set up a PeerConnection and
  send a synthetic video (color bars) and optional sine audio.
- GET or HEAD /call/webrtc_local: Returns 405 (method not allowed) to signal presence, matching
  the integration's probe behavior.

Requires: aiohttp, aiortc, av, numpy

Usage:
  python3 tools/creality_webrtc_test_server.py --host 0.0.0.0 --port 8000

In Home Assistant, set the integration host to your machine's IP. The integration will hit:
  http://<host>:8000/call/webrtc_local

Optional args:
  --fps 20 --width 640 --height 360 --no-audio

This is for local testing only.
"""
from __future__ import annotations
import asyncio
import argparse
import base64
import json
import logging
import math
import os
import signal
from typing import Optional

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaBlackhole
import av
import numpy as np
from fractions import Fraction

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("creality_webrtc_test_server")

CALL_PATH = "/call/webrtc_local"

class SyntheticVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, width: int = 640, height: int = 360, fps: int = 20):
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self._ts = 0
        self._frame_dur = 1 / fps
        self._t0 = asyncio.get_event_loop().time()
        self._video_pts = 0
        self._video_time_base = Fraction(1, fps)

    async def recv(self):
        await asyncio.sleep(self._frame_dur)
        t = asyncio.get_event_loop().time() - self._t0
        # moving color bars + time overlay
        img = self._bars(self.width, self.height, t)
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        # Set pts/time_base so aiortc encoder can encode frames
        frame.pts = int(self._video_pts)
        frame.time_base = self._video_time_base
        self._video_pts += 1
        
        # Log every 30th frame to avoid spam
        if self._video_pts % 30 == 0:
            LOGGER.info("Generated video frame %d at time %.1fs (%.1f fps)", 
                       self._video_pts, t, self._video_pts / t if t > 0 else 0)
        
        return frame

    def _bars(self, w: int, h: int, t: float) -> np.ndarray:
        # Create a background with moving color bars
        x = np.linspace(0, 1, w, dtype=np.float32)
        y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        r = (np.sin(2 * math.pi * (x + 0.1 * t)) * 0.5 + 0.5)
        g = (np.sin(2 * math.pi * (x * 0.5 + 0.07 * t)) * 0.5 + 0.5)
        b = (np.sin(2 * math.pi * (x * 0.25 + 0.05 * t)) * 0.5 + 0.5)
        img = np.stack([
            np.broadcast_to(r, (h, w)),
            np.broadcast_to(g, (h, w)),
            np.broadcast_to(b, (h, w)),
        ], axis=-1)
        # add a faint vertical gradient
        img *= (0.7 + 0.3 * y)[:, :, None]
        img = np.clip(img * 255, 0, 255).astype(np.uint8)
        
        # Add rotating text overlay
        img = self._add_rotating_text(img, w, h, t)
        
        return img
    
    def _add_rotating_text(self, img: np.ndarray, w: int, h: int, t: float) -> np.ndarray:
        """Add rotating text overlay to the image."""
        # Text to display
        text = "CREALITY K2 WEBCAM STREAM"
        words = text.split()
        
        # Calculate rotation angle (full rotation every 10 seconds)
        angle = (t * 2 * math.pi / 10) % (2 * math.pi)
        
        # Center of rotation
        center_x, center_y = w // 2, h // 2
        
        # Create a copy to work with
        result = img.copy()
        
        # Draw each word at different positions around the circle
        for i, word in enumerate(words):
            # Calculate position for this word
            word_angle = angle + (i * 2 * math.pi / len(words))
            radius = min(w, h) // 4
            
            # Position of this word
            word_x = int(center_x + radius * math.cos(word_angle))
            word_y = int(center_y + radius * math.sin(word_angle))
            
            # Draw simple text (using basic pixel manipulation)
            result = self._draw_text(result, word, word_x, word_y, (255, 255, 255))
        
        # Add a central time display
        time_text = f"Time: {t:.1f}s"
        result = self._draw_text(result, time_text, center_x - 50, center_y + 50, (255, 255, 0))
        
        # Add frame counter
        frame_text = f"Frame: {int(t * self.fps)}"
        result = self._draw_text(result, frame_text, center_x - 50, center_y + 70, (0, 255, 255))
        
        return result
    
    def _draw_text(self, img: np.ndarray, text: str, x: int, y: int, color: tuple) -> np.ndarray:
        """Draw simple text on the image using basic pixel manipulation."""
        # Simple 8x8 pixel font for each character
        char_width = 8
        char_height = 8
        
        for i, char in enumerate(text):
            char_x = x + (i * char_width)
            char_y = y
            
            # Skip if character would be outside image bounds
            if char_x + char_width > img.shape[1] or char_y + char_height > img.shape[0] or char_x < 0 or char_y < 0:
                continue
                
            # Draw a simple representation of the character
            if char == 'C':
                # Draw 'C' shape
                for dy in range(2, char_height-2):
                    img[char_y + dy, char_x + 1] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
            elif char == 'R':
                # Draw 'R' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height//2, char_x + dx] = color
                for dy in range(char_height//2, char_height):
                    img[char_y + dy, char_x + char_width-2] = color
            elif char == 'E':
                # Draw 'E' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height//2, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
            elif char == 'A':
                # Draw 'A' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                    img[char_y + dy, char_x + char_width-2] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height//2, char_x + dx] = color
            elif char == 'L':
                # Draw 'L' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                for dx in range(1, char_width-1):
                    img[char_y + char_height-2, char_x + dx] = color
            elif char == 'I':
                # Draw 'I' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + char_width//2] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
            elif char == 'T':
                # Draw 'T' shape
                for dx in range(char_width):
                    img[char_y + 1, char_x + dx] = color
                for dy in range(1, char_height):
                    img[char_y + dy, char_x + char_width//2] = color
            elif char == 'Y':
                # Draw 'Y' shape
                for dy in range(char_height//2):
                    img[char_y + dy, char_x + dy] = color
                    img[char_y + dy, char_x + char_width-1-dy] = color
                for dy in range(char_height//2, char_height):
                    img[char_y + dy, char_x + char_width//2] = color
            elif char == 'K':
                # Draw 'K' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                for dy in range(char_height//2):
                    img[char_y + dy, char_x + char_width-1-dy] = color
                for dy in range(char_height//2, char_height):
                    img[char_y + dy, char_x + 2 + (dy - char_height//2)] = color
            elif char == '2':
                # Draw '2' shape
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
                for dy in range(1, char_height//2):
                    img[char_y + dy, char_x + char_width-2] = color
                for dy in range(char_height//2, char_height-1):
                    img[char_y + dy, char_x + 1] = color
            elif char == 'W':
                # Draw 'W' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                    img[char_y + dy, char_x + char_width-2] = color
                for dy in range(char_height//2, char_height):
                    img[char_y + dy, char_x + char_width//2] = color
            elif char == 'B':
                # Draw 'B' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height//2, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
                for dy in range(1, char_height//2):
                    img[char_y + dy, char_x + char_width-2] = color
                for dy in range(char_height//2, char_height-1):
                    img[char_y + dy, char_x + char_width-2] = color
            elif char == 'M':
                # Draw 'M' shape
                for dy in range(char_height):
                    img[char_y + dy, char_x + 1] = color
                    img[char_y + dy, char_x + char_width-2] = color
                for dy in range(char_height//2):
                    img[char_y + dy, char_x + char_width//2] = color
            elif char == 'S':
                # Draw 'S' shape
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height//2, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
                for dy in range(1, char_height//2):
                    img[char_y + dy, char_x + 1] = color
                for dy in range(char_height//2, char_height-1):
                    img[char_y + dy, char_x + char_width-2] = color
            elif char == ' ':
                # Space - do nothing
                pass
            else:
                # For other characters, draw a simple box
                for dy in range(2, char_height-2):
                    img[char_y + dy, char_x + 1] = color
                    img[char_y + dy, char_x + char_width-2] = color
                for dx in range(1, char_width-1):
                    img[char_y + 1, char_x + dx] = color
                    img[char_y + char_height-2, char_x + dx] = color
        
        return img

class SyntheticAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, samplerate: int = 48000, tone_hz: float = 440.0):
        super().__init__()
        self.samplerate = samplerate
        self.tone_hz = tone_hz
        self._t = 0.0
        self._audio_pts = 0
        self._audio_time_base = Fraction(1, samplerate)

    async def recv(self):
        await asyncio.sleep(0.02)
        # generate 20ms of sine
        samples = int(self.samplerate * 0.02)
        t = (np.arange(samples) + self._t) / self.samplerate
        self._t += samples
        data = 0.1 * np.sin(2 * math.pi * self.tone_hz * t)
        # av expects a 2D ndarray for audio: (channels, samples)
        pcm = (data * 32767).astype(np.int16)
        pcm2 = np.expand_dims(pcm, axis=0)  # shape (1, samples) for mono
        frame = av.AudioFrame.from_ndarray(pcm2, format="s16", layout="mono")
        frame.sample_rate = self.samplerate
        # pts should be in sample frames
        frame.pts = int(self._audio_pts)
        frame.time_base = self._audio_time_base
        self._audio_pts += samples
        
        # Log every 50th audio frame to avoid spam
        if self._audio_pts % (samples * 50) == 0:
            LOGGER.info("Generated audio frame %d samples at %.1fHz", 
                       self._audio_pts, self.tone_hz)
        
        return frame

class Session:
    def __init__(self, pc: RTCPeerConnection, sink: Optional[MediaBlackhole] = None):
        self.pc = pc
        self.sink = sink

    async def close(self):
        if self.sink:
            await self.sink.stop()
        await self.pc.close()

class Server:
    def __init__(self, host: str, port: int, width: int, height: int, fps: int, audio: bool):
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.audio = audio
        self.app = web.Application()
        self.app.add_routes([
            web.post(CALL_PATH, self.handle_call),
            web.get(CALL_PATH, self.handle_probe),
        ])
        self._sessions: set[Session] = set()

    async def handle_probe(self, request: web.Request):
        # Creality printers typically answer 405 to GET/HEAD on this endpoint.
        return web.Response(status=405, text="Method Not Allowed")

    async def handle_call(self, request: web.Request):
        try:
            peer = request.remote
            LOGGER.debug("Received POST /call from %s", peer)
            body_b64 = await request.text()
            LOGGER.debug("Raw body length=%d", len(body_b64))
            payload = json.loads(base64.b64decode(body_b64).decode("utf-8"))
            LOGGER.debug("Decoded payload keys=%s", list(payload.keys()))
            if payload.get("type") != "offer" or "sdp" not in payload:
                LOGGER.warning("Invalid offer payload from %s: %s", peer, payload)
                return web.Response(status=400, text="invalid payload")
            offer_sdp = payload["sdp"]
            LOGGER.info("Offer SDP length=%d from %s", len(offer_sdp or ""), peer)
        except Exception as exc:
            LOGGER.exception("Failed to parse offer: %s", exc)
            return web.Response(status=400, text="bad request")

        pc = RTCPeerConnection()
        LOGGER.debug("Created RTCPeerConnection id=%s", id(pc))
        @pc.on("connectionstatechange")
        def _on_connstate():
            try:
                LOGGER.info("PC(%s) connectionState=%s", id(pc), pc.connectionState)
            except Exception:
                pass
        @pc.on("iceconnectionstatechange")
        def _on_ice():
            try:
                LOGGER.info("PC(%s) iceConnectionState=%s", id(pc), pc.iceConnectionState)
            except Exception:
                pass
        @pc.on("datachannel")
        def _on_datachannel(channel):
            try:
                LOGGER.info("PC(%s) received data channel: %s", id(pc), channel.label)
            except Exception:
                pass
        # First, set the remote description to see what media the client is offering
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        
        # Detect which media types are in the offer
        offer_has_video = "m=video" in offer_sdp
        offer_has_audio = "m=audio" in offer_sdp
        
        LOGGER.info("Offer has video=%s, audio=%s", offer_has_video, offer_has_audio)
        
        # Only add tracks for media types present in the offer
        if offer_has_video:
            video_track = SyntheticVideoTrack(self.width, self.height, self.fps)
            pc.addTrack(video_track)
            LOGGER.info("Added video track: %dx%d @ %dfps", self.width, self.height, self.fps)
        
        if offer_has_audio and self.audio:
            audio_track = SyntheticAudioTrack()
            pc.addTrack(audio_track)
            LOGGER.info("Added audio track: %dHz sine wave", audio_track.samplerate)

        # Note: If the client sends any incoming tracks, sink them to blackhole
        sink = MediaBlackhole()
        @pc.on("track")
        async def on_track(track):
            LOGGER.info("Received remote track kind=%s id=%s", track.kind, getattr(track, 'id', None))
            await sink.start()
            sink.addTrack(track)

        # Generate answer (remote description was already set above)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        LOGGER.info("Created answer SDP length=%d for PC id=%s", len(pc.localDescription.sdp or ""), id(pc))

        session = Session(pc, sink)
        self._sessions.add(session)
        # Debug: log answer SDP with visible escapes and JSON/base64 representations
        try:
            sdp = pc.localDescription.sdp or ""
            LOGGER.debug("Answer SDP repr=%r", sdp)
            LOGGER.debug("Answer SDP escaped=%s", sdp.replace("\n", "\\n"))
            payload = {"type": "answer", "sdp": sdp}
            LOGGER.debug("Answer JSON payload=%s", json.dumps(payload)[:1000])
            out = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
            LOGGER.debug("Answer base64 len=%d", len(out))
        except Exception:
            out = base64.b64encode(json.dumps({"type": "answer", "sdp": pc.localDescription.sdp}).encode("utf-8")).decode("ascii")
        # Schedule cleanup later (client may disconnect on its own)
        asyncio.create_task(self._cleanup_later(session))
        return web.Response(status=200, text=out, headers={"Content-Type": "plain/text"})

    async def _cleanup_later(self, session: Session):
        # keep connections alive for a while, then close if idle
        await asyncio.sleep(60)
        try:
            await session.close()
        finally:
            self._sessions.discard(session)

    def run(self):
        web.run_app(self.app, host=self.host, port=self.port)


def main():
    parser = argparse.ArgumentParser(description="Creality WebRTC test server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    if args.debug:
        LOGGER.setLevel(logging.DEBUG)
        logging.getLogger("aiohttp.server").setLevel(logging.DEBUG)
        logging.getLogger("aiortc").setLevel(logging.DEBUG)
        LOGGER.debug("Debug logging enabled")

    srv = Server(args.host, args.port, args.width, args.height, args.fps, audio=not args.no_audio)
    srv.run()

if __name__ == "__main__":
    main()
