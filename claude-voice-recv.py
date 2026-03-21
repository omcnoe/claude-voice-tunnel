#!/usr/bin/env python3
import socket, subprocess, os, threading, shutil, time

os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
os.environ['PULSE_SERVER'] = 'unix:/run/user/1000/pulse/native'

PORT = 9257
lock = threading.Lock()
active = [None, None]  # [conn, pacat]


def _is_running(name):
    """Check if a process is running by name."""
    try:
        subprocess.run(['pgrep', '-x', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True) # check=True checks for non-zero exit code
        return True
    except subprocess.CalledProcessError:
        return False

def _start_daemon(name):
    """Start a daemon if not already running."""
    if _is_running(name):
        print(f'{name} already running', flush=True)
        return
    print(f'Starting {name}...', flush=True)
    subprocess.Popen([name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _ensure_null_sink():
    """Create the claude_mic null sink if it doesn't exist."""
    result = subprocess.run(['pactl', 'list', 'sinks', 'short'],
                            capture_output=True, text=True)
    if 'claude_mic' in result.stdout:
        print('claude_mic sink already exists', flush=True)
        return
    print('Creating claude_mic null sink...', flush=True)
    subprocess.run([
        'pactl', 'load-module', 'module-null-sink',
        'sink_name=claude_mic',
        'sink_properties=device.description="Claude_Voice_Tunnel_Microphone"',
        'format=s16le', 'rate=16000', 'channels=1'
    ], check=True)
    subprocess.run(['pactl', 'set-default-source', 'claude_mic.monitor'], check=True)

def ensure_audio():
    """Start PipeWire daemons and create null sink if needed."""
    for daemon in ['pipewire', 'wireplumber', 'pipewire-pulse']:
        if not shutil.which(daemon):
            print(f'WARNING: {daemon} not found on PATH', flush=True)
            return
    _start_daemon('pipewire')
    time.sleep(0.3)
    _start_daemon('wireplumber')
    time.sleep(0.3)
    _start_daemon('pipewire-pulse')
    time.sleep(0.5)  # let pulse socket come up
    _ensure_null_sink()

def handle(conn, addr):
    print(f'Connection from {addr}', flush=True)
    # Wait for first data before taking over — proves this is a real sender
    try:
        first = conn.recv(2048)
        if not first:
            conn.close()
            return
    except Exception:
        conn.close()
        return

    print(f'Audio from {addr}, taking over', flush=True)
    pacat = subprocess.Popen(
        ['pacat', '--playback', '--format=s16le', '--rate=16000',
         '--channels=1', '--device=claude_mic',
         '--latency-msec=1'],
        stdin=subprocess.PIPE)

    # Now replace the old connection
    with lock:
        old_conn, old_pacat = active
        active[0] = conn
        active[1] = pacat
    if old_pacat:
        old_pacat.terminate()
    if old_conn:
        try:
            old_conn.close()
        except Exception:
            pass

    try:
        pacat.stdin.write(first)
        pacat.stdin.flush()
        while True:
            data = conn.recv(2048)
            if not data:
                break
            pacat.stdin.write(data)
            pacat.stdin.flush()
    except Exception as e:
        print(f'Connection ended: {e}', flush=True)
    finally:
        pacat.terminate()
        conn.close()

ensure_audio()

srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
srv.bind(('::', PORT))
srv.listen(5)
print(f'Listening on port {PORT}', flush=True)

while True:
    conn, addr = srv.accept()
    conn.settimeout(5)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
