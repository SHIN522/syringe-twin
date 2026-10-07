"""Real HTTP contract adapter and SQLite persistence verification."""
import sqlite3
from fastapi.testclient import TestClient
from twin.api import create_app
from twin.service import Service


def client_service(tmp_path):
    srv=Service(tmp_path)
    app=create_app(srv)
    app.state.service=srv
    return TestClient(app),srv


def test_http_commands_live_and_traceability(tmp_path):
    client,srv=client_service(tmp_path)
    assert client.get('/api/health').json()['ok']
    assert client.post('/api/commands',json={'cmd':'start','user':'QA'}).status_code==200
    with srv.lock:
        srv.engine.advance(100)
        srv.sample()
    live=client.get('/api/live').json()
    assert live['snapshot']['counts']['good']>0
    assert live['kpi']['check']['conservation']
    rows=client.get('/api/parts').json()
    assert client.get('/api/parts/'+rows[0]['serial']).json()['events']
    assert client.get('/api/parts/no-such-part').status_code==404
    assert client.get('/api/commands').json()[0]['user']=='QA'
    with sqlite3.connect(srv.historian.path) as con:
        assert con.execute('SELECT count(*) FROM parts').fetchone()[0]>0
        assert con.execute('SELECT count(*) FROM part_events').fetchone()[0]>0
        assert con.execute('SELECT user FROM commands').fetchone()[0]=='QA'


def test_http_rejects_invalid_speed_and_estop_restart(tmp_path):
    client,srv=client_service(tmp_path)
    response=client.post('/api/commands',json={'cmd':'set_speed','args':{'x':99},'user':'QA'})
    assert response.status_code==409
    client.post('/api/commands',json={'cmd':'estop','args':{'active':True},'user':'QA'})
    assert client.post('/api/commands',json={'cmd':'start','user':'QA'}).status_code==409


def test_motion_endpoint_is_fresh_and_light(tmp_path):
    client,srv=client_service(tmp_path)
    client.post('/api/commands',json={'cmd':'start','user':'QA'})
    with srv.lock:
        srv.engine.advance(30)  # no sample() call: /api/live would still be stale
    motion=client.get('/api/motion').json()
    assert motion['snapshot']['t']==srv.engine.state.t
    assert {'transfers','station_progress','pallets','empty_queue','parts','last_decision'} <= set(motion['meta'])
    assert all(v['status'] in ('WIP','PASS','FAIL') for v in motion['meta']['parts'].values())
    assert all(1<=pid<=10 for pid in motion['meta']['empty_queue'])
