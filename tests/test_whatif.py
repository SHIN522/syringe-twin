"""What-if sandbox: isolation, fairness, decisions and the HTTP route."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from twin.api import create_app
from twin.engine import Engine
from twin.service import Service
from twin.whatif import run_whatif, design_capacity
from test_operational import state_fingerprint


@pytest.fixture(scope='module')
def worn():
    """Default demo config after 20 sim-minutes: S2 wear is high, F201 is close."""
    e = Engine()
    e.command('start', user='QA')
    e.advance(1200)
    return e


def test_live_twin_is_untouched(worn):
    before = state_fingerprint(worn.state)
    result = run_whatif(deepcopy(worn.state), 'maintenance', horizon_s=1800)
    assert state_fingerprint(worn.state) == before
    json.dumps(result, allow_nan=False)


def test_results_are_deterministic(worn):
    a = run_whatif(deepcopy(worn.state), 'maintenance', horizon_s=1800)
    b = run_whatif(deepcopy(worn.state), 'maintenance', horizon_s=1800)
    assert [arm['kpi']['good'] for arm in a['arms']] == [arm['kpi']['good'] for arm in b['arms']]


def test_keep_running_forecast_matches_the_live_future(worn):
    """Replication 1 continues the twin's own random sequence, so it forecasts the live line."""
    result = run_whatif(deepcopy(worn.state), 'maintenance', horizon_s=1800)
    forecast = result['arms'][0]['kpi']['first_f201_s']
    live = deepcopy(worn)
    start = live.state.t
    while live.state.faults_s2 == worn.state.faults_s2:
        live.tick()
    assert live.state.t - start == pytest.approx(forecast, abs=0.11)


def test_condition_based_maintenance_is_recommended(worn):
    result = run_whatif(deepcopy(worn.state), 'maintenance', horizon_s=3600, replications=3)
    keep, _, policy = (arm['kpi'] for arm in result['arms'])
    assert policy['f201'] < keep['f201']
    assert policy['reject'] < keep['reject']
    assert policy['good'] > keep['good']
    assert result['recommendation']['arm'] == 'condition_based'
    assert result['recommendation']['wins'] == 3


def test_faster_non_bottleneck_gives_no_gain(worn):
    result = run_whatif(deepcopy(worn.state), 'cycle_time',
                        {'station': 'S1', 'step': 'CURE', 'value': 2.0}, horizon_s=1800)
    current, modified = (arm['kpi'] for arm in result['arms'])
    assert modified['good'] == pytest.approx(current['good'], abs=2)
    assert result['recommendation']['arm'] == 'current'
    assert modified['design']['bottleneck'] == 'S2'


def test_faster_bottleneck_gains_and_moves_design_bottleneck(worn):
    result = run_whatif(deepcopy(worn.state), 'cycle_time',
                        {'station': 'S2', 'step': 'INSERT', 'value': 0.5}, horizon_s=1800)
    current, modified = (arm['kpi'] for arm in result['arms'])
    assert modified['good'] > current['good'] * 1.1
    assert modified['design']['bottleneck'] == 'S1'
    assert result['recommendation']['arm'] == 'modified'


def test_design_capacity_matches_brief():
    capacity = design_capacity(Engine().state.config)
    assert capacity['bottleneck'] == 'S2'
    assert capacity['rate_ph'] == pytest.approx(360)


@pytest.mark.parametrize('scenario,params,horizon,reps', [
    ('unknown', {}, 3600, 1),
    ('cycle_time', {'station': 'S9', 'step': 'CURE', 'value': 2}, 3600, 1),
    ('cycle_time', {'station': 'S1', 'step': 'CURE', 'value': 0}, 3600, 1),
    ('cycle_time', {'station': 'S1', 'step': 'CURE', 'value': True}, 3600, 1),
    ('maintenance', {}, 99, 1),
    ('maintenance', {}, 3600, 7)])
def test_invalid_requests_rejected(scenario, params, horizon, reps):
    with pytest.raises(ValueError):
        run_whatif(Engine().state, scenario, params, horizon, reps)


def test_http_whatif_route(tmp_path):
    service = Service(tmp_path)
    app = create_app(service)
    app.state.service = service
    client = TestClient(app)
    service.command('start', {}, 'QA')
    service.engine.advance(300)
    before = service.engine.state.t
    options = client.get('/api/whatif/scenarios').json()
    assert options['cycle_time']['params']['steps']['S1']['CURE'] == 3.0
    response = client.post('/api/whatif', json={'scenario': 'maintenance', 'horizon_s': 1800})
    assert response.status_code == 200
    assert len(response.json()['arms']) == 3
    assert service.engine.state.t == before
    bad = client.post('/api/whatif', json={'scenario': 'maintenance', 'horizon_s': 5})
    assert bad.status_code == 409
