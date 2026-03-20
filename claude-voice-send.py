#!/usr/bin/env python3
"""claude-voice-send - streams mic audio to claude-voice-recv."""

import subprocess
import sys
import time
import socket
import threading
import signal
import re

HOST = "localhost"
PORT = 9257
CHECK_INTERVAL = 5

def list_audio_devices():
    """List available audio input devices via ffmpeg/dshow."""
    proc = subprocess.run(
        ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    devices = []
    for line in proc.stderr.splitlines():
        if "Alternative name" in line:
            continue
        m = re.search(r'"(.+?)"\s+\(audio\)', line)
        if m:
            devices.append(m.group(1))
    return devices

def pick_device():
    """Let user pick an audio device."""
    devices = list_audio_devices()
    if not devices:
        print("No audio devices found.", flush=True)
        sys.exit(1)
    if len(devices) == 1:
        print(f"Using: {devices[0]}", flush=True)
        return devices[0]
    print("Audio devices:", flush=True)
    for i, d in enumerate(devices):
        print(f"  {i + 1}. {d}", flush=True)
    while True:
        try:
            choice = int(input("Select device: "))
            if 1 <= choice <= len(devices):
                return devices[choice - 1]
        except (ValueError, EOFError):
            pass
        print(f"Enter 1-{len(devices)}", flush=True)

def ffmpeg_cmd(device):
    return [
        "ffmpeg",
        "-hide_banner",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-f", "dshow",
        "-rtbufsize", "1k",
        "-i", f"audio={device}",
        "-af", "aresample=16000",
        "-f", "s16le",
        "-ar", "16000",
        "-ac", "1",
        "-flush_packets", "1",
        f"tcp://{HOST}:{PORT}",
    ]

def watchdog(proc):
    """Kill ffmpeg if the server becomes unreachable."""
    while proc.poll() is None:
        time.sleep(CHECK_INTERVAL)
        try:
            s = socket.create_connection((HOST, PORT), timeout=2)
            s.close()
        except OSError:
            print("Lost connection, restarting ffmpeg", flush=True)
            proc.kill()
            return

def main():
    if "--list" in sys.argv:
        for d in list_audio_devices():
            print(d)
        return

    device = pick_device()
    proc = None

    def shutdown(sig, frame):
        print("\nStopped.", flush=True)
        if proc:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    while True:
        print(f"Starting ffmpeg -> {HOST}:{PORT}", flush=True)
        try:
            proc = subprocess.Popen(ffmpeg_cmd(device))
            threading.Thread(target=watchdog, args=(proc,), daemon=True).start()
            proc.wait()
            print(f"ffmpeg exited with code {proc.returncode}", flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(1)

if __name__ == "__main__":
    main()
