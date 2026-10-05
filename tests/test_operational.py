"""Browser/API integration checks for the local operational package."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import base64
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from twin.api import create_app
from twin.engine import Engine
from twin.service import Service


def stationary_client(tmp_path):
    """A deliberately unpaced service isolates reads from engine scheduling."""
    service = Service(tmp_path)
    app = create_app(service)
    app.state.service = service
    return TestClient(app), service


def state_fingerprint(state):
    return deepcopy((state.t, state.run, state.counts, state.pallets,
                     state.buffers, state.transfers, state.stations,
                     state.parts, state.commands, list(state.events),
                     {name: rng.bit_generator.state
                      for name, rng in state.rng.items()}))


def test_dashboard_reads_never_advance_or_mutate_the_model(tmp_path):
    client, service = stationary_client(tmp_path)
    service.command('start', {}, 'Browser QA')
    service.engine.advance(100)
    service.sample()
    baseline = state_fingerprint(service.engine.state)
    serial = next(iter(service.engine.state.parts))
    for _ in range(3):
        for path in ('/api/live', '/api/snapshot', '/api/kpi', '/api/parts',
                     '/api/parts/' + serial, '/api/alarms', '/api/commands',
                     '/api/events', '/api/health'):
            response = client.get(path)
            assert response.status_code == 200, path
            json.dumps(response.json(), allow_nan=False)
    assert state_fingerprint(service.engine.state) == baseline


def test_animation_metadata_tracks_real_pallets_and_process_progress():
    engine = Engine()
    engine.command('start', user='Browser QA')
    active_stations = set()
    saw_transfer = False
    for _ in range(150):
        engine.advance(1)
        state = engine.state
        payload = engine.payload()
        meta = payload['meta']
        assert meta['pallets'] == state.pallets
        assert len(meta['pallets']) == state.config['pallets'] == 10
        assert meta['transfers'] == [asdict(tr) for tr in state.transfers]
        for transfer in meta['transfers']:
            saw_transfer = True
            assert transfer['pallet'] in meta['pallets']
            assert 0 <= transfer['remaining'] <= transfer['total']
            expected = (state.config['return_s']
                        if transfer['destination'] == 'RETURN'
                        else state.config['transfer_s'])
            assert transfer['total'] == expected
        for name, station in state.stations.items():
            progress = meta['station_progress'][name]
            assert progress['pallet'] == station.pallet
            assert progress['elapsed'] == station.elapsed
            if progress['duration'] is None:
                assert progress['progress'] is None
            else:
                assert progress['duration'] > 0
                assert 0 <= progress['progress'] <= 1
                if progress['elapsed'] > 0:
                    active_stations.add(name)
            if station.pallet is not None:
                assert payload['snapshot']['stations'][name]['part'] == meta['pallets'][station.pallet]
        assert payload['kpi']['check']['conservation']
        assert payload['kpi']['check']['pallet_conservation']
        json.dumps(payload, allow_nan=False)
    assert saw_transfer
    assert active_stations == set(engine.state.stations)


class LocalAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        candidate = (attributes.get('src') if tag == 'script'
                     else attributes.get('href') if tag == 'link' else None)
        if candidate and not urlsplit(candidate).scheme and not candidate.startswith('//'):
            self.paths.append(urljoin('/', candidate))


def test_browser_entrypoint_assets_and_api_share_one_origin(tmp_path):
    client, _ = stationary_client(tmp_path)
    homepage = client.get('/')
    assert homepage.status_code == 200
    assert homepage.headers['content-type'].startswith('text/html')
    assert 'SyringeTwin' in homepage.text
    parser = LocalAssets()
    parser.feed(homepage.text)
    assert parser.paths, 'The browser entrypoint must reference its local assets.'
    for path in parser.paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 0
    worker = client.get('/sim-worker.js')
    assert worker.status_code == 200
    assert 'javascript' in worker.headers['content-type']
    model = client.get('/model_bundle.json')
    assert model.status_code == 200
    assert 'twin/engine.py' in model.json()['files']
    health = client.get('/api/health')
    assert health.status_code == 200
    assert health.json()['ok'] is True
    assert client.post('/api/commands', json={
        'cmd': 'start', 'args': {}, 'user': 'Browser QA'
    }).json()['ok'] is True
    assert client.get('/api/live').json()['snapshot']['run'] is True
    assert client.get('/api/no-such-route').status_code == 404


def test_browser_bundle_matches_local_engine_and_has_working_indian_timezone():
    root = Path(__file__).resolve().parents[1]
    bundle = json.loads((root / 'web' / 'model_bundle.json').read_text(encoding='utf-8'))
    assert bundle['files']
    assert set(bundle['files']) == set(bundle['sha256'])
    for name, bundled_source in bundle['files'].items():
        source = root / name
        assert source.resolve().is_relative_to(root.resolve())
        assert bundled_source == source.read_text(encoding='utf-8'), name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == bundle['sha256'][name], name
    timezone_bytes = base64.b64decode(bundle['binary_files']['zoneinfo/Asia/Kolkata'], validate=True)
    assert timezone_bytes.startswith(b'TZif')
    timezone = ZoneInfo.from_file(BytesIO(timezone_bytes), key='Asia/Kolkata')
    assert datetime(2026, 10, 5, tzinfo=timezone).utcoffset() == timedelta(hours=5, minutes=30)
