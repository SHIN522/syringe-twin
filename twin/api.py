"""HTTP adapter; snapshot keys and operator command shape follow brief section 8.

Added read endpoints replace MQTT transport for the authorized Streamlit MVP.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .service import Service


class Command(BaseModel):
    cmd: str
    args: dict = Field(default_factory=dict)
    user: str = Field(min_length=1, max_length=80)


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or Service(os.getenv('SYRINGETWIN_DATA_DIR','data'))
        app.state.service.start()
        yield
        app.state.service.close()

    app = FastAPI(title='SyringeTwin', version='0.2-browser', lifespan=lifespan)

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

    web = Path(__file__).resolve().parents[1] / 'web'
    if web.is_dir():
        app.mount('/', StaticFiles(directory=web, html=True), name='dashboard')
    return app


app = create_app()
