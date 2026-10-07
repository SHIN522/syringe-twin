"""HTTP adapter; snapshot keys and operator command shape follow brief section 8.

Dashboards poll /api/live over HTTP; /api/whatif runs the decision-support sandbox.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .service import Service
from .whatif import run_whatif, scenarios
from .plc_bridge import from_env
from .model import load_config


def opcua_from_env(value):
    """SYRINGETWIN_OPCUA=1 (default endpoint) or an opc.tcp:// endpoint enables the server."""
    if not value or value == '0':
        return None
    from .opcua_server import OpcUaServer, ENDPOINT
    return OpcUaServer(value if value.startswith('opc.tcp://') else ENDPOINT)


class Command(BaseModel):
    cmd: str
    args: dict = Field(default_factory=dict)
    user: str = Field(min_length=1, max_length=80)


class WhatIf(BaseModel):
    scenario: str
    params: dict = Field(default_factory=dict)
    horizon_s: int = 3600
    replications: int = 1


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or Service(os.getenv('SYRINGETWIN_DATA_DIR','data'),
                                               config=load_config(os.getenv('SYRINGETWIN_PROFILE') or None),
                                               plc=from_env(os.getenv('SYRINGETWIN_PLC')),
                                               opcua=opcua_from_env(os.getenv('SYRINGETWIN_OPCUA')))
        app.state.service.start()
        yield
        app.state.service.close()

    app = FastAPI(title='SyringeTwin', version='1.0', lifespan=lifespan)

    @app.get('/api/health')
    def health():
        srv = app.state.service
        return {'ok': srv.last_error is None, 'engine_error':srv.last_error,
                'transport':'HTTP', 't': srv.engine.state.t,
                'instance_id': os.getenv('SYRINGETWIN_INSTANCE_ID')}

    @app.get('/api/live')
    def live():
        srv = app.state.service
        with srv.lock:
            data = deepcopy(srv.latest)
            data['history'] = list(srv.history)
            data['meta']['engine_error'] = srv.last_error
            return data

    @app.get('/api/motion')
    def motion():
        """Fresh, light state for 3D viewers that poll faster than the 2 Hz live sample."""
        srv = app.state.service
        with srv.lock:
            s = srv.engine.state
            p = srv.engine.payload()
            m, k = p['meta'], p['kpi']
            on_pallets = [serial for serial in s.pallets.values() if serial]
            decided = [part for part in s.parts.values() if part.status != 'WIP']
            last = max(decided, key=lambda part: part.t_out or 0, default=None)
            return {'snapshot': {key: p['snapshot'][key] for key in
                                 ('t', 'run', 'speed', 'lamp', 'stations', 'buffers', 'counts', 'alarms')},
                    'meta': {**{key: m[key] for key in ('transfers', 'station_progress', 'pallets',
                                                        'estop_active', 'estop_latched')},
                             'empty_queue': list(s.empty),
                             'parts': {serial: {'status': s.parts[serial].status,
                                                'codes': s.parts[serial].reject_codes} for serial in on_pallets},
                             'plc': srv.bridge.status(s) if srv.bridge else {'mode': 'internal'},
                             'tool_ok': m['tool_ok'],
                             'last_decision': None if last is None else
                                 {'serial': last.serial, 'status': last.status, 'codes': last.reject_codes}},
                    'kpi': {'th_ph': k['th_ph'], 'Q': k['Q'], 'oee_win': k['oee_win']['oee']}}

    @app.get('/api/snapshot')
    def snapshot():
        return live()['snapshot']

    @app.get('/api/kpi')
    def kpi():
        return live()['kpi']

    @app.post('/api/commands')
    def command(payload: Command):
        try:
            return app.state.service.command(payload.cmd,payload.args,payload.user)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/parts')
    def parts(status: str | None = None, limit: int = Query(50,ge=1,le=1000)):
        srv = app.state.service
        with srv.lock:
            rows = list(srv.engine.state.parts.values())
            return [asdict(p) for p in reversed(rows) if status is None or p.status==status][:limit]

    @app.get('/api/parts/{serial}')
    def part(serial: str):
        srv = app.state.service
        with srv.lock:
            if serial not in srv.engine.state.parts:
                raise HTTPException(404,'Serial not found in this simulation run.')
            return asdict(srv.engine.state.parts[serial])

    def log(name,limit):
        srv = app.state.service
        with srv.lock:
            return deepcopy(list(getattr(srv.engine.state,name))[-limit:][::-1])

    @app.get('/api/alarms')
    def alarms(limit: int = Query(100,ge=1,le=1000)):
        return log('alarms',limit)

    @app.get('/api/commands')
    def commands(limit: int = Query(100,ge=1,le=1000)):
        return log('commands',limit)

    @app.get('/api/events')
    def events(limit: int = Query(50,ge=1,le=200)):
        return log('events',limit)

    whatif_busy = Lock()

    @app.get('/api/whatif/scenarios')
    def whatif_scenarios():
        srv = app.state.service
        with srv.lock:
            return scenarios(deepcopy(srv.engine.state.config))

    @app.post('/api/whatif')
    def whatif(payload: WhatIf):
        srv = app.state.service
        if not whatif_busy.acquire(blocking=False):
            raise HTTPException(409, 'A what-if analysis is already running.')
        try:
            # Copy under the lock, simulate outside it: the live line keeps running.
            with srv.lock:
                if srv.last_error:
                    raise HTTPException(409, 'Engine halted: ' + srv.last_error)
                state = deepcopy(srv.engine.state)
            return run_whatif(state, payload.scenario, payload.params,
                              payload.horizon_s, payload.replications)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            whatif_busy.release()

    web = Path(__file__).resolve().parents[1] / 'web'
    if web.is_dir():
        app.mount('/', StaticFiles(directory=web, html=True), name='dashboard')
    return app


app = create_app()
