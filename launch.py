"""Launch both dashboards; retain an owned, stoppable background session on Windows."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
STATE = RUNTIME / 'server.json'
STOP = RUNTIME / 'stop.json'


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is in use. Choose --api-port and --ui-port, or stop the earlier app.') from exc


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def health(url):
    with urllib.request.urlopen(url + '/api/health', timeout=2) as response:
        return json.load(response)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_ready(url, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('A service exited during startup. Check .runtime logs or console output.')
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError('Service startup timed out. Check .runtime logs or console output.')


def urls(options):
    return f'http://127.0.0.1:{options.api_port}', f'http://127.0.0.1:{options.ui_port}'


def stop_owned():
    state = read_json(STATE)
    if not state:
        print('No managed SyringeTwin session is recorded.')
        return 0
    try:
        live = health(state['url'])
    except (OSError, ValueError):
        print('Recorded session is already offline.')
        return 0
    if live.get('instance_id') != state.get('instance_id'):
        raise RuntimeError('Recorded port belongs to another session; it was left running.')
    STOP.write_text(json.dumps({'instance_id': state['instance_id']}), encoding='utf-8')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if read_json(STATE).get('instance_id') != state['instance_id']:
            print('SyringeTwin stopped. Simulation history remains in data/.')
            return 0
        time.sleep(0.2)
    raise RuntimeError('Stop request sent, but shutdown has not completed. Check .runtime logs.')


def background(options):
    existing = read_json(STATE)
    if existing:
        try:
            live = health(existing['url'])
            if live.get('instance_id') == existing.get('instance_id'):
                print(f"SyringeTwin is already running: {existing['url']}")
                if not options.no_browser:
                    webbrowser.open(existing['url'])
                return 0
        except (OSError, ValueError, KeyError):
            pass
    free_port(options.api_port)
    free_port(options.ui_port)
    RUNTIME.mkdir(exist_ok=True)
    command = [sys.executable, str(ROOT / 'launch.py'), '--no-browser',
               '--api-port', str(options.api_port), '--ui-port', str(options.ui_port)]
    if options.plc:
        command += ['--plc', options.plc]
    if options.profile:
        command += ['--profile', options.profile]
    if options.opcua:
        command += ['--opcua']
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    with (RUNTIME / 'stdout.log').open('a', encoding='utf-8') as output, (RUNTIME / 'stderr.log').open('a', encoding='utf-8') as error:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=error, creationflags=flags,
                                   start_new_session=os.name != 'nt')
    api_url, ui_url = urls(options)
    wait_ready(api_url + '/api/health', process)
    wait_ready(ui_url + '/_stcore/health', process)
    print(f'SyringeTwin is running in the background.\nSimulation: {api_url}\nStreamlit: {ui_url}\nStop: python launch.py --stop')
    if not options.no_browser:
        webbrowser.open(api_url)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--ui-port', type=int, default=8501)
    parser.add_argument('--profile', choices=['demo'],
                        help='Configuration profile from config/profiles (demo: fresh tool, accelerated wear)')
    parser.add_argument('--opcua', action='store_true',
                        help='serve the twin read-only over OPC UA at opc.tcp://127.0.0.1:4840/syringetwin/')
    parser.add_argument('--plc', metavar='HOST[:PORT]',
                        help='PLC mode: link the twin to OpenPLC Runtime over Modbus TCP')
    options = parser.parse_args()
    backend = dashboard = None
    instance_id = uuid.uuid4().hex
    try:
        if options.stop:
            return stop_owned()
        if not 1 <= options.api_port <= 65535 or not 1 <= options.ui_port <= 65535 or options.api_port == options.ui_port:
            raise RuntimeError('API and UI ports must be distinct integers from 1 to 65535.')
        if options.background:
            return background(options)
        free_port(options.api_port)
        free_port(options.ui_port)
        api_url, ui_url = urls(options)
        env = dict(os.environ, SYRINGETWIN_API_PORT=str(options.api_port),
                   SYRINGETWIN_API_URL=api_url, SYRINGETWIN_INSTANCE_ID=instance_id)
        if options.plc:
            env['SYRINGETWIN_PLC'] = options.plc
        if options.profile:
            env['SYRINGETWIN_PROFILE'] = options.profile
        if options.opcua:
            env['SYRINGETWIN_OPCUA'] = '1'
        RUNTIME.mkdir(exist_ok=True)
        backend = subprocess.Popen([sys.executable, '-m', 'twin'], cwd=ROOT, env=env)
        wait_ready(api_url + '/api/health', backend)
        dashboard = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'streamlit_app.py',
            '--server.address=127.0.0.1', f'--server.port={options.ui_port}'], cwd=ROOT, env=env)
        wait_ready(ui_url + '/_stcore/health', dashboard)
        STATE.write_text(json.dumps({'instance_id': instance_id, 'pid': os.getpid(),
            'api_pid': backend.pid, 'ui_pid': dashboard.pid, 'url': api_url, 'streamlit_url': ui_url}), encoding='utf-8')
        print(f'\nSyringeTwin ready. Simulation: {api_url} | Streamlit: {ui_url}\nPress Start in either dashboard. Ctrl+C or Stop_Windows.bat stops both.', flush=True)
        if not options.no_browser:
            webbrowser.open(api_url)
        while backend.poll() is None and dashboard.poll() is None:
            if read_json(STOP).get('instance_id') == instance_id:
                return 0
            time.sleep(0.2)
        raise RuntimeError('A service stopped unexpectedly. Check its output.')
    except KeyboardInterrupt:
        print('\nClosing SyringeTwin...')
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        stop(dashboard)
        stop(backend)
        if read_json(STATE).get('instance_id') == instance_id:
            STATE.unlink(missing_ok=True)
        if read_json(STOP).get('instance_id') == instance_id:
            STOP.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
