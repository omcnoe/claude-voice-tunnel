# Claude voice tunnel

Forward a local microphone to a remote Linux VM, so Claude Code's `/voice` works over SSH.

## Architecture

```
Client (Windows/Linux)      Server (Linux)
----------------------      --------------
Microphone                  Claude /voice
    |                           ^
    v                           |
claude-voice-send.py        ALSA capture
    |                           ^
    v                           |
ffmpeg (dshow/pulse)        claude_mic.monitor
    |                           ^
    v                           |
s16le 16kHz mono           PipeWire null sink (claude_mic)
    |                           ^
    v                           |
localhost:9257              claude-voice-recv.py
    |                           ^
    |                           |
    -------> port forward -------
```

## Server Setup (Linux)

**Note, this might break your system audio!**

Linux audio is notoriously a nightmare.
Claude voice tunnel is really intended for ephemeral claude code dev environments (containers, gh codespaces, etc) where consequence of misconfiguring audio is very low.
Tested on Debian 13.

### 1. Install audio packages

```bash
sudo apt-get update && sudo apt-get install -y pipewire pipewire-pulse wireplumber libasound2-plugins pulseaudio-utils alsa-utils
```

PipeWire with `pipewire-pulse` provides PulseAudio protocol compatibility. The `support.null-audio-sink` factory includes its own timer-based driver, so it works headless without kernel sound modules.

### 2. Set ALSA default to PulseAudio

```bash
sudo cp /etc/alsa/conf.d/99-pulseaudio-default.conf.example /etc/alsa/conf.d/99-pulseaudio-default.conf
```

Claude Code uses ALSA directly (`snd_pcm_*`) for audio capture, not PulseAudio. The `libasound2-plugins` package installs the ALSA-to-PulseAudio bridge plugin but does not activate it as the default. Without this, ALSA fails with `Unknown PCM default` in headless environments that have no kernel sound devices.

### 3. Env vars

```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse/native"

sudo mkdir -p -m 700 "$XDG_RUNTIME_DIR"
sudo chown $(id -u):$(id -g) "$XDG_RUNTIME_DIR"


echo '' >> ~/.bashrc
echo '# claude-voice-tunnel' >> ~/.bashrc
echo 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"' >> ~/.bashrc
echo 'export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse/native"' >> ~/.bashrc
```

### 4. Low-latency PipeWire config

```bash
mkdir -p ~/.config/pipewire/pipewire-pulse.conf.d

cat > ~/.config/pipewire/pipewire-pulse.conf.d/low-latency.conf << 'EOF'
pulse.properties = {
    pulse.default.tlength = 1600/16000   # 100ms
    pulse.default.frag    = 320/16000    # 20ms
    pulse.min.tlength     = 320/16000    # 20ms
    pulse.min.frag        = 160/16000    # 10ms
    pulse.min.quantum     = 160/16000    # 10ms
}
EOF
```

PipeWire's PulseAudio layer seems to have terrible latency in default config. This override drops it to 20ms.

It's deliberate choice to use raw PCM instead of a codec like opus, to minimize latency.

### 5. Start TCP audio receiver

`claude-voice-recv.py` auto-starts PipeWire, WirePlumber, and pipewire-pulse if they aren't already running, then creates the `claude_mic` null sink. Just run:

```bash
python3 -u claude-voice-recv.py
```

RTKit warnings about `MaxRealtimePriority` are harmless in containers - PipeWire falls back to non-realtime scheduling.

### 6. Launch Claude Code in a new shell

```bash
claude
```

## Client Setup (Linux/Windows)

`ffmpeg`, `python3`/`python.exe` binaries must be on `$PATH`.

On Linux, `pactl` (from `pulseaudio-utils`) is also needed.

The script auto-detects the platform - uses DirectShow (`dshow`) on Windows and PulseAudio (`pulse`) source on Linux.

```bash
python3 claude-voice-send.py
```

```
python.exe claude-voice-send.py
```

### Port forwarding

```bash
ssh -L 9257:localhost:9257 <host>
```
