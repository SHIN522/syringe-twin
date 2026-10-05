/* Original Python Engine in a Web Worker; this is a transport/pacing adapter, not a second model. */
'use strict';
const PYODIDE_VERSION = '0.29.3';
const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
let python = null, initialized = null, pulse = null, last = 0, credit = 0, sampled = 0, halted = false;
let clock = {dt:.1,speed:10};
const status = (message) => postMessage({type:'status',message});

const ADAPTER = String.raw`
import sys, json
from collections import deque
from dataclasses import asdict
from twin.engine import Engine
from twin.control import scan
from twin.events import wall_time

_web_engine = Engine()
_web_history = deque(maxlen=300)
_web_error = None

def _web_sample():
    payload = _web_engine.payload()
    payload['meta']['published_wall'] = wall_time()
    payload['meta']['engine_error'] = _web_error
    payload['meta']['database'] = None
    k = payload['kpi']
    _web_history.append({
        't': k['t'], 'throughput': k['th_ph'],
        'force_N': payload['snapshot']['stations']['S2']['force'],
        'oee_pct': k['oee'] * 100 if k['oee'] is not None else None
    })
    payload['history'] = list(_web_history)
    return json.dumps(payload)

def _web_live():
    payload = _web_engine.payload()
    payload['meta']['published_wall'] = wall_time()
    payload['meta']['engine_error'] = _web_error
    payload['meta']['database'] = None
    payload['history'] = list(_web_history)
    return json.dumps(payload)

def _web_steps(n):
    for _ in range(n):
        _web_engine.tick()

def _web_command():
    request = json.loads(_web_request)
    if _web_error:
        raise ValueError('Engine halted: ' + _web_error)
    result = _web_engine.command(request['cmd'], request.get('args', {}), request.get('user', ''))
    if not _web_engine.state.run:
        scan(_web_engine.state)
    return json.dumps(result)

def _web_read():
    request = json.loads(_web_request)
    path = request['path']
    pathname, _, query = path.partition('?')
    s = _web_engine.state
    if pathname == 'live':
        return _web_live()
    if pathname == 'health':
        return json.dumps({'ok': _web_error is None, 'engine_error': _web_error, 'transport': 'Browser worker', 't': s.t})
    if pathname == 'snapshot':
        return json.dumps(_web_engine.snapshot())
    if pathname == 'kpi':
        return json.dumps(_web_engine.payload()['kpi'])
    params = {}
    for item in query.split('&'):
        k, sep, v = item.partition('=')
        if sep:
            params[k] = v
    limit = min(1000, max(1, int(params.get('limit', 50))))
    if pathname == 'parts':
        rows = list(s.parts.values())
        return json.dumps([asdict(part) for part in reversed(rows)
                          if params.get('status') is None or part.status == params['status']][:limit])
    if pathname.startswith('parts/'):
        serial = pathname.split('/', 1)[1]
        if serial not in s.parts:
            raise ValueError('Serial not found in this simulation run.')
        return json.dumps(asdict(s.parts[serial]))
    if pathname in ('alarms', 'commands', 'events'):
        return json.dumps(list(getattr(s, pathname))[-limit:][::-1])
    raise ValueError('Unsupported browser endpoint: ' + pathname)

_web_sample()
`;

function installFile(path,source,binary = false) {
  if (path.startsWith('/') || path.split('/').includes('..')) throw new Error('Invalid model bundle path.');
  const target = `/app/${path}`, parent = target.slice(0,target.lastIndexOf('/'));
  python.FS.mkdirTree(parent);
  if (binary) {
    const raw = atob(source), bytes = Uint8Array.from(raw,(ch) => ch.charCodeAt(0));
    python.FS.writeFile(target,bytes);
  } else python.FS.writeFile(target,source,{encoding:'utf8'});
}
async function init() {
  status('Loading the Python runtime · first visits may take a moment.');
  importScripts(`${PYODIDE_INDEX}pyodide.js`);
  python = await loadPyodide({indexURL:PYODIDE_INDEX});
  status('Loading NumPy and YAML support for the original simulation.');
  await python.loadPackage(['numpy','pyyaml']);
  status('Loading the verified Python source and cell configuration.');
  const response = await fetch(new URL('./model_bundle.json',self.location.href),{cache:'no-cache'});
  if (!response.ok) throw new Error(`Could not load model bundle (${response.status}).`);
  const bundle = await response.json(), files = bundle.files || bundle;
  if (!files['twin/engine.py'] || !files['config/line.yaml']) throw new Error('The model bundle is incomplete. Rebuild it from the Python source.');
  python.FS.mkdirTree('/app');
  for (const [path,source] of Object.entries(files)) installFile(path,source);
  for (const [path,source] of Object.entries(bundle.binary_files || {})) installFile(path,source,true);
  if (bundle.binary_files?.['zoneinfo/Asia/Kolkata']) {
    python.runPython("import zoneinfo\nzoneinfo.reset_tzpath(['/app/zoneinfo'])");
  } else {
    status('Loading timezone data for the operator audit.');
    await python.loadPackage('tzdata');
  }
  python.runPython("import sys\nsys.path.insert(0, '/app')");
  python.runPython(ADAPTER);
  clock = JSON.parse(python.runPython("json.dumps({'dt':_web_engine.state.config['dt'],'speed':_web_engine.state.speed})"));
  last = sampled = performance.now();
  postMessage({type:'ready',runtime:`Pyodide ${PYODIDE_VERSION}`,model_sha256:bundle.sha256 || null});
  publish(false);
  pulse = setInterval(pace,40);
}
function publish(sample = true) {
  const payload = JSON.parse(python.runPython(sample ? '_web_sample()' : '_web_live()'));
  postMessage({type:'snapshot',payload});
}
function pace() {
  if (!python || halted) return;
  const now = performance.now();
  try {
    // Same bounded wall-time credit and fixed dt as the local Service; no background catch-up leap.
    credit += Math.min((now-last)/1000,.5)*clock.speed;
    const count = Math.floor((credit+1e-10)/clock.dt);
    if (count > 0) {
      python.globals.set('_web_n',count); python.runPython('_web_steps(_web_n)'); credit -= count*clock.dt;
    }
    last = now;
    if (now-sampled >= 500) {publish(); sampled = now;}
  } catch (error) {
    halted = true; clearInterval(pulse);
    python.globals.set('_web_error',String(error.message || error));
    python.runPython('_web_engine.state.run = False');
    try {publish();} catch (_) {/* Fatal message remains available even when serialization fails. */}
    postMessage({type:'fatal',error:`Python simulation halted: ${error.message || error}`});
  }
}
function userMessage(error) {
  const message = String(error.message || error);
  const match = message.match(/(?:ValueError|KeyError):\s*([^\n]+)/);
  return match ? match[1] : message;
}
self.onmessage = async ({data}) => {
  if (data.type === 'init') {
    if (!initialized) initialized = init();
    try {await initialized;}
    catch (error) {halted = true; postMessage({type:'fatal',error:`Browser simulation could not start: ${userMessage(error)}. Check your internet connection and retry.`});}
    return;
  }
  try {
    if (!initialized) throw new Error('The browser engine is not initialized.');
    await initialized;
    if (halted) throw new Error('The browser engine is halted; retry the connection.');
    if (data.type === 'command') {
      python.globals.set('_web_request',JSON.stringify({cmd:data.cmd,args:data.args || {},user:data.user || ''}));
      const payload = JSON.parse(python.runPython('_web_command()'));
      clock.speed = Number(python.runPython('_web_engine.state.speed'));
      publish(); sampled = performance.now();
      postMessage({id:data.id,payload});
    } else if (data.type === 'read') {
      const path = data.path.startsWith('parts/') ? `parts/${decodeURIComponent(data.path.slice(6))}` : data.path;
      python.globals.set('_web_request',JSON.stringify({path}));
      postMessage({id:data.id,payload:JSON.parse(python.runPython('_web_read()'))});
    } else throw new Error('Unsupported worker message.');
  } catch (error) {
    postMessage({id:data.id,error:userMessage(error),rejected:/ValueError:/.test(String(error.message || error))});
  }
};
