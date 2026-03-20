#!/usr/bin/env python3
import socket, subprocess, os, threading

os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
os.environ['PULSE_SERVER'] = 'unix:/run/user/1000/pulse/native'

PORT = 9257
lock = threading.Lock()
active = [None, None]  # [conn, pacat]

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
