"""Run against a local backend in the same process environment."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time
import os
import requests
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def run():
    env=dict(os.environ,SYRINGETWIN_API_PORT='8012',SYRINGETWIN_API_URL='http://127.0.0.1:8012',
             SYRINGETWIN_DATA_DIR=tempfile.mkdtemp(prefix='syringetwin-ui-'))
    os.environ['SYRINGETWIN_API_URL']=env['SYRINGETWIN_API_URL']
    backend=subprocess.Popen([sys.executable,'-m','twin'],cwd=ROOT,env=env)
    checks=[]
    try:
        for _ in range(100):
            try:
                if requests.get(env['SYRINGETWIN_API_URL']+'/api/health',timeout=1).ok: break
            except requests.RequestException: time.sleep(0.1)
        at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
        assert not at.exception, str(at.exception)
        assert at.title[0].value=='Syringe assembly cell'
        assert len(at.metric)>=9
        checks.append('Initial live dashboard renders with controls and measured KPI tiles')
        at.button(key='start').click().run()
        assert not at.exception, str(at.exception)
        time.sleep(2)
        at.run()
        data=requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()
        assert data['snapshot']['run'] and data['snapshot']['counts']['in']>0
        checks.append('Start button drives backend and produces real serials')
        for page in ['Trends','Alarms & audit','Traceability','Maintenance']:
            at.radio[0].set_value(page).run()
            assert not at.exception, str(at.exception)
            checks.append(page+' renders')
        at.radio[0].set_value('Live cell').run()
        at.button(key='estop').click().run()
        assert not at.exception,str(at.exception)
        assert requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()['meta']['estop_active']
        checks.append('E-stop button reaches backend')
        at.button(key='estop').click().run()
        at.button(key='reset').click().run()
        at.button(key='start').click().run()
        assert not at.exception,str(at.exception)
        assert requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()['snapshot']['run']
        checks.append('Release → Reset → Start recovery works from dashboard')
        at.radio[0].set_value('Maintenance').run()
        # Wait for an active S2 cycle, then use the actual dashboard fault button.
        # 1x speed keeps S2 mid-cycle for ~8 s wall, so a slow CI runner cannot miss the window.
        requests.post(env['SYRINGETWIN_API_URL']+'/api/commands',json={'cmd':'set_speed','args':{'x':1},'user':'QA'})
        for _ in range(200):
            d=requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()
            s2=d['snapshot']['stations']['S2']
            if s2['state']=='RUNNING' and s2['step'] in ('PRESS','INSERT'): break
            time.sleep(0.1)
        at.button(key='inject').click().run()
        assert not at.exception,str(at.exception)
        d=requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()
        assert any(a['code']=='F201' for a in d['snapshot']['alarms'])
        assert d['snapshot']['run']
        checks.append('Dashboard Inject F201 creates a local S2 fault')
        at.button(key='repair').click().run()
        requests.post(env['SYRINGETWIN_API_URL']+'/api/commands',json={'cmd':'set_speed','args':{'x':50},'user':'QA'})
        for _ in range(80):
            d=requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()
            if d['meta']['tool_ok']: break
            time.sleep(0.1)
        assert d['meta']['tool_ok']
        at.button(key='reset').click().run()
        assert not at.exception,str(at.exception)
        assert not any(a['code']=='F201' for a in requests.get(env['SYRINGETWIN_API_URL']+'/api/live').json()['snapshot']['alarms'])
        checks.append('Dashboard Repair → wait → Reset clears F201')
        backend.terminate()
        backend.wait(timeout=10)
        at.run()
        assert not at.exception,str(at.exception)
        assert any('unavailable' in x.value for x in at.error)
        checks.append('Disconnected state hides live values and offers retry')
        return checks
    finally:
        if backend.poll() is None:
            backend.terminate()
            backend.wait(timeout=10)


if __name__=='__main__':
    print(json.dumps({'checks':run()},indent=2))
