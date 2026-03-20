# Claude voice tunnel - microphone forwarding for Claude Code voice dictation

Forward a local microphone to a remote Linux VM, so Claude Code's `/voice` works over SSH.

## Architecture

```
Windows
-------
Microphone
    |
    v
claude-voice-send.py
    |
    v
ffmpeg (dshow)
    |
    v
s16le 16kHz mono
    |                            Linux
    v                            -----
localhost:5555 --port forward--> claude-voice-recv.py
                                     |
                                     v
                                 pacat --playback
                                     |
                                     v
                                 PipeWire null sink (claude_mic)
                                     |
                                     v
                                 claude_mic.monitor
                                     |
                                     v
                                 ALSA -> Claude /voice
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

### 5. Start PipeWire

```bash
pipewire &
wireplumber &
pipewire-pulse &
```

RTKit warnings about `MaxRealtimePriority` are harmless in containers - PipeWire falls back to non-realtime scheduling.

### 6. Create null sink

```bash
pactl load-module module-null-sink \
  sink_name=claude_mic \
  sink_properties=device.description="Claude_Voice_Tunnel_Microphone" \
  format=s16le rate=16000 channels=1

pactl set-default-source claude_mic.monitor
```

This creates:
- A sink (`claude_mic`) that accepts audio playback
- A monitor source (`claude_mic.monitor`) that exposes played audio as a capture device

The monitor source becomes the default capture device that Claude's native module reads from.

### 7. Start TCP audio receiver

Run `claude-voice-recv.py` (see file for source):

```bash
python3 -u claude-voice-recv.py
```

### 8. Launch Claude Code

```bash
claude
```

## Client Setup (Windows)

### Send audio

Run `claude-voice-send.py` (see file for source):

```bash
python claude-voice-send.py
```

TODO support non-Windows clients. Probably just need to swap dshow out in ffmpeg.

### Port forwarding

```bash
ssh -L 9257:localhost:9257 <host>
```
