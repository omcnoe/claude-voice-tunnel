#!/usr/bin/env python3
"""claude-voice-send - streams mic audio to claude-voice-recv."""

import subprocess
import sys
import time
import socket
import signal
import re
import platform

IS_WINDOWS = platform.system() == "Windows"

HOST = "localhost"
PORT = 9257

def list_audio_devices():
    """List available audio input devices. Exits if none found."""
    if IS_WINDOWS:
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
    else:
        proc = subprocess.run(
            ["pactl", "list", "short", "sources"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        devices = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                devices.append(parts[1])
    if not devices:
        print("No audio devices found.", flush=True)
        sys.exit(1)
    return devices

def print_devices(devices):
    """Print numbered device list."""
    for i, d in enumerate(devices):
        print(f"  {i + 1}. {d}", flush=True)

def pick_device(choice=None):
    """Let user pick an audio device, or select by number."""
    devices = list_audio_devices()
    if choice is not None and 1 <= choice <= len(devices):
        print(f"Using: {devices[choice - 1]}", flush=True)
        return devices[choice - 1]
    if len(devices) == 1:
        print(f"Using: {devices[0]}", flush=True)
        return devices[0]
    print_devices(devices)
    while True:
        try:
            choice = int(input("Select device: "))
            if 1 <= choice <= len(devices):
                print(f"Using: {devices[choice - 1]}", flush=True)
                return devices[choice - 1]
        except (ValueError, EOFError):
            pass
        print(f"Enter 1-{len(devices)}", flush=True)

def ffmpeg_cmd(device):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
    ]
    if IS_WINDOWS:
        cmd += ["-f", "dshow", "-rtbufsize", "1k", "-i", f"audio={device}"]
    else:
        cmd += ["-f", "pulse", "-i", device]
    cmd += [
        "-af", "aresample=16000",
        "-f", "s16le",
        "-ar", "16000",
        "-ac", "1",
        "-flush_packets", "1",
        "pipe:1",
    ]
    return cmd

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--list" in sys.argv:
        print_devices(list_audio_devices())
        return

    device = pick_device(int(args[0]) if args else None)
    proc = None

    def shutdown(sig, frame):
        print("\nStopped.", flush=True)
        if proc:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    while True:
        # Connect to server first
        try:
            sock = socket.create_connection((HOST, PORT), timeout=2)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(2)
            sock.sendall(b'PING')
            if sock.recv(16) != b'PONG':
                raise OSError("Server handshake failed")
        except OSError as e:
            print(f"Cannot connect to {HOST}:{PORT}: {e}", flush=True)
            time.sleep(1)
            continue

        print(f"Connected, starting ffmpeg", flush=True)
        try:
            proc = subprocess.Popen(ffmpeg_cmd(device),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
            while True:
                data = proc.stdout.read(512)
                if not data:
                    break
                sock.sendall(data)
        except (OSError, BrokenPipeError, socket.timeout) as e:
            print(f"Connection lost: {e}", flush=True)
        finally:
            proc.kill()
            proc.wait()
            try:
                sock.close()
            except Exception:
                pass
        time.sleep(1)

if __name__ == "__main__":
    main()
