/* Read-only animation interpolates model observations. Only the Python engine advances time. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = (value, precision = 1) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('en-US', {maximumFractionDigits:precision, minimumFractionDigits:precision});
  const percent = (value) => value == null ? '—' : fmt(value * 100);
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const pages = {
    live:['Syringe assembly cell','A live view of every station, pallet and production decision.'],
    trends:['Production performance','Measured quality, throughput and availability across the simulation.'],
    alarms:['Alarms & audit','Every alarm, operator action and process event in this run.'],
    trace:['Part traceability','Follow a serial from material input to its inspection outcome.'],
    maintenance:['Cell maintenance','Manage the press tool, recover faults and replenish material.'],
    plc:['PLC logic','The supervisory logic of the cell as ladder rungs, side by side with the Structured Text it is compiled from.'],
    decide:['Decision support','Copy the live twin, change one decision, run it forward and compare before acting.']
  };
  let currentPage = pages[location.hash.slice(1)] ? location.hash.slice(1) : 'live';
  let latest = null, engine = null, ready = false, requestBusy = false, connected = false;
  let lastSnapshotAt = 0, lastLogAt = 0, logsBusy = false, tracePart = null;
  let auditRows = [], recentParts = [], commandSequence = 0;
  let retryTimer = null, pollTimer = null, staleTimer = null;
  const mode = new URLSearchParams(location.search).get('engine');
  const localHost = ['localhost','127.0.0.1','[::1]'].includes(location.hostname);
  const browserMode = mode === 'browser' || (!localHost && mode !== 'local');
  const operatorStorage = 'syringetwin.operator';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  class LocalEngine {
    async request(path, method = 'GET', body, timeoutMs = 5000) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(`/api/${path}`, {method, headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined, signal:controller.signal, cache:'no-store'});
        const payload = await response.json();
        if (!response.ok) {
          const detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail ?? payload);
          const error = new Error(detail); error.rejected = true; throw error;
        }
        return payload;
      } catch (error) {
        if (error.name === 'AbortError') throw new Error('The local engine did not respond. Delivery is unconfirmed; check the audit before repeating a command.');
        throw error;
      } finally { clearTimeout(timeout); }
    }
    read(path) { return this.request(path); }
    command(cmd, args, user) { return this.request('commands','POST',{cmd,args,user}); }
  }

  class BrowserEngine {
    constructor() {
      this.worker = new Worker(new URL('./sim-worker.js', location.href));
      this.pending = new Map(); this.sequence = 0;
      this.initialized = new Promise((resolve, reject) => { this.resolveReady = resolve; this.rejectReady = reject; });
      this.worker.onmessage = ({data}) => {
        if (data.type === 'status') { notice('Loading browser simulation',data.message); return; }
        if (data.type === 'ready') { this.resolveReady(); return; }
        if (data.type === 'snapshot') { acceptSnapshot(data.payload); return; }
        if (data.type === 'fatal') {
          this.rejectReady(new Error(data.error));
          for (const promise of this.pending.values()) { clearTimeout(promise.timer); promise.reject(new Error(data.error)); }
          this.pending.clear(); disconnect(data.error); return;
        }
        const pending = this.pending.get(data.id);
        if (!pending) return;
        this.pending.delete(data.id); clearTimeout(pending.timer);
        if (data.error) { const error = new Error(data.error); error.rejected = data.rejected === true; pending.reject(error); }
        else pending.resolve(data.payload);
      };
      this.worker.onerror = (event) => {
        const error = new Error(event.message || 'The browser worker could not load.');
        this.rejectReady(error); disconnect(error.message);
      };
      this.worker.postMessage({type:'init'});
    }
    async send(type, payload = {}) {
      await this.initialized;
      const id = ++this.sequence;
      return new Promise((resolve,reject) => {
        const timer = setTimeout(() => {this.pending.delete(id); reject(new Error('Browser engine response timed out. Command delivery is unconfirmed; inspect the audit before retrying.'));},12000);
        this.pending.set(id,{resolve,reject,timer}); this.worker.postMessage({id,type,...payload});
      });
    }
    read(path) { return this.send('read',{path}); }
    command(cmd,args,user) { return this.send('command',{cmd,args,user}); }
    close() { this.worker.terminate(); }
  }

  function setValue(name,value) { document.querySelectorAll(`[data-value="${name}"]`).forEach((el) => {el.textContent = value;}); }
  function notice(title,text,error = false) {
    $('runtime-notice').hidden = false; $('runtime-notice').classList.toggle('error',error);
    $('runtime-notice-title').textContent = title; $('runtime-notice-text').textContent = text;
    $('retry').hidden = !error; $('browser-fallback').hidden = browserMode || !error;
  }
  function feedback(text,kind = 'success') {
    $('feedback').hidden = false; $('feedback').className = `feedback ${kind}`; $('feedback').textContent = text;
  }
  function updateConnection(value) {
    connected = value;
    $('connection-label').innerHTML = `<span class="status-dot ${value ? 'green' : 'red'}"></span>${value ? 'Engine connected' : 'Connection lost'}`;
    $('side-dot').className = `status-dot ${value ? 'green' : 'red'}`;
    $('side-engine').textContent = browserMode ? 'Browser simulation' : 'Local engine';
    $('side-subtitle').textContent = value ? (browserMode ? 'Private to this browser tab' : 'Shared local simulation') : 'Waiting for fresh data';
    document.body.classList.toggle('stale',!value);
  }
  function disconnect(message) {
    ready = false; updateConnection(false); updateControls();
    $('line-state-label').textContent = 'DISCONNECTED'; $('line-state').querySelector('.status-dot').className = 'status-dot red';
    notice('Simulation unavailable',message || 'Cannot reach the engine. Displayed readings are stale; controls are unavailable until it reconnects.',true);
  }
  async function boot() {
    clearTimeout(retryTimer); clearTimeout(pollTimer); clearInterval(staleTimer);
    ready = false; updateControls();
    if (engine instanceof BrowserEngine) engine.close();
    $('engine-tag').textContent = browserMode ? 'Browser simulation' : 'Local engine';
    $('side-engine').textContent = browserMode ? 'Browser simulation' : 'Local engine';
    $('mode-footnote').textContent = browserMode ? 'Tab-local simulation · Refresh starts a new run · Export records before closing' : 'Simulated process controls · No physical hardware connected';
    try {
      if (browserMode) {
        notice('Loading browser simulation','Loading the original Python model. The first visit downloads the Python runtime; this may take a little time.');
        engine = new BrowserEngine(); await engine.initialized;
        acceptSnapshot(await engine.read('live'));
      } else {
        notice('Connecting to the local engine','Connecting to the simulation service on this computer.');
        engine = new LocalEngine();
        const health = await engine.read('health');
        if (!health.ok) throw new Error(health.engine_error || 'The local engine reported an error.');
        acceptSnapshot(await engine.read('live')); poll();
      }
      staleTimer = setInterval(() => {
        if (connected && performance.now() - lastSnapshotAt > 6500) disconnect('The engine stopped publishing fresh readings. Controls are disabled; retry the connection.');
      },1000);
    } catch (error) {
      disconnect(error.message);
      if (!browserMode) retryTimer = setTimeout(boot,4000);
    }
  }
  async function poll() {
    try { acceptSnapshot(await engine.read('live')); }
    catch (error) { disconnect(error.rejected ? error.message : 'Cannot reach the local engine. Start the Windows launcher or check its terminal, then retry.'); }
    pollTimer = setTimeout(poll,500);
  }
  function acceptSnapshot(data) {
    if (!data || !data.snapshot || !data.kpi || !data.meta) { disconnect('The engine returned an incomplete snapshot.'); return; }
    if (data.meta.engine_error) { disconnect(`Engine halted: ${data.meta.engine_error}`); return; }
    if (!browserMode && data.meta.published_wall) {
      const age = Date.now() - Date.parse(data.meta.published_wall);
      if (Number.isFinite(age) && age > 8000) { disconnect('The local engine snapshot is stale. Restart the service to recover.'); return; }
    }
    latest = data; ready = true; lastSnapshotAt = performance.now(); updateConnection(true);
    $('runtime-notice').hidden = true;
    render(data); updateControls();
    if (['alarms','trace'].includes(currentPage) && performance.now() - lastLogAt > 1800) loadPageRecords();
    if (currentPage === 'decide' && !scenarioOptions) loadScenarios();
  }
  function updateControls() {
    const s = latest?.snapshot, m = latest?.meta;
    document.querySelectorAll('[data-command]').forEach((el) => {el.disabled = !ready || requestBusy;});
    $('start').disabled = !ready || requestBusy || s?.run || m?.estop_latched;
    $('stop').disabled = !ready || requestBusy || !s?.run;
    $('estop').disabled = !ready || requestBusy;
    $('speed').disabled = !ready || requestBusy;
    $('estop-text').textContent = m?.estop_active ? 'Release E-stop' : 'Emergency stop';
    $('estop').classList.toggle('release',m?.estop_active === true);
  }
  async function sendCommand(cmd,args = {}) {
    const user = $('operator').value.trim();
    if (!user) {
      feedback('Enter your operator name before sending a command.','error');
      document.querySelector('.operator-field').classList.add('invalid'); $('operator').focus();
      if (cmd === 'set_speed' && latest) $('speed').value = latest.snapshot.speed;
      return;
    }
    if (!ready || !engine || requestBusy) { feedback('The engine is unavailable. Wait for a fresh connection before sending a command.','error'); return; }
    const sequence = ++commandSequence;
    requestBusy = true; updateControls(); feedback(`Sending ${cmd.replaceAll('_',' ')}…`,'pending');
    let acknowledged = false;
    try {
      const result = await engine.command(cmd,args,user);
      if (!result?.ok) throw new Error(result?.message || 'The engine did not confirm the command. Inspect the audit before retrying.');
      acknowledged = true;
      feedback(result.message || 'Command accepted.');
      acceptSnapshot(await engine.read('live'));
      if (['alarms','trace'].includes(currentPage)) await loadPageRecords(true);
    } catch (error) {
      if (sequence === commandSequence) feedback(`${acknowledged ? 'Command accepted; live refresh failed' : error.rejected ? 'Command rejected' : 'Delivery unconfirmed'}: ${error.message}`,'error');
      if (cmd === 'set_speed' && latest) $('speed').value = latest.snapshot.speed;
    } finally { requestBusy = false; updateControls(); }
  }

  function navigate(page) {
    if (!pages[page]) page = 'live'; currentPage = page;
    document.querySelectorAll('.page').forEach((el) => el.classList.toggle('active',el.id === `page-${page}`));
    document.querySelectorAll('.nav-button').forEach((el) => {el.classList.toggle('active',el.dataset.page === page); el.setAttribute('aria-current',el.dataset.page === page ? 'page' : 'false');});
    $('page-title').innerHTML = `${esc(pages[page][0])}<span class="heading-dot">.</span>`;
    $('page-description').textContent = pages[page][1];
    if (location.hash !== `#${page}`) history.replaceState(null,'',`${location.pathname}${location.search}#${page}`);
    if (latest) render(latest);
    if (['alarms','trace'].includes(page)) loadPageRecords(true);
    if (page === 'decide') loadScenarios();
  }

  function render({snapshot:s,kpi:k,meta:m,history:h = []}) {
    const state = m.estop_latched ? 'E-STOP LATCHED' : s.run ? 'LINE RUNNING' : 'LINE STOPPED';
    $('line-state-label').textContent = state;
    $('line-state').querySelector('.status-dot').className = `status-dot ${s.lamp === 'RED' ? 'red' : s.lamp === 'AMBER' ? 'amber' : s.run ? 'green' : ''}`;
    $('sim-time').textContent = `${fmt(s.t / 60)} sim-min`; $('state-speed').textContent = `${s.speed}×`;
    $('speed').value = String(s.speed);
    $('recovery').hidden = !m.estop_latched;
    $('recovery').querySelector('strong').textContent = m.estop_active ? 'E-stop active · release it to recover' : 'E-stop released · reset the latch';
    setValue('throughput',fmt(k.th_ph,0)); setValue('window',fmt(k.win_s,0)); setValue('oee',percent(k.oee)); setValue('oee-win',percent(k.oee_win?.oee)); setValue('quality',percent(k.Q));
    setValue('wip',fmt(s.counts.wip,0)); setValue('empty',fmt(m.empty_pallets,0)); setValue('loaded',fmt(s.counts.in,0));
    setValue('good',fmt(s.counts.good,0)); setValue('reject',fmt(s.counts.reject,0)); setValue('boxes',fmt(s.counts.boxes,0));
    setValue('force',fmt(s.stations.S2.force)); setValue('unplanned',fmt(k.down_s.S2.unplanned)); setValue('planned',fmt(k.down_s.S2.planned));
    setValue('availability',percent(k.A)); setValue('performance',percent(k.P)); setValue('line-cycle',fmt(k.line_ct_s)); setValue('lead',fmt(k.lead_s)); setValue('wip-average',fmt(k.wip_avg));
    setValue('health',percent(k.s2.health)); setValue('cycles-to-fault',fmt(k.s2.cycles_to_fault,0)); setValue('maintenance-time',fmt(m.maintenance_remaining_s));
    $('health-progress').style.width = `${Math.max(0,Math.min(100,k.s2.health*100))}%`;
    const conserved = k.check.conservation && k.check.pallet_conservation;
    $('conservation').innerHTML = `${icon(conserved ? 'check' : 'alert')}${conserved ? 'Parts & 10 unique pallets conserved' : 'Conservation check failed'}`;
    $('conservation').classList.toggle('failed',!conserved);
    $('alarm-count').textContent = s.alarms.length; $('nav-alarm-count').textContent = s.alarms.length; $('nav-alarm-count').hidden = s.alarms.length === 0;
    $('active-alarms').innerHTML = s.alarms.length ? s.alarms.map((a) => `<div class="active-alarm">${icon('alert')}<div><strong>${esc(a.code)}<span class="severity ${esc(a.sev)}">${esc(a.sev)}</span></strong><p>${esc(a.text)}</p><small>Since ${fmt(a.since)} sim-s</small></div></div>`).join('') : `<div class="empty-state compact-empty"><span class="empty-check">${icon('check')}</span><strong>All clear</strong><p>No active alarms in this cell.</p></div>`;
    renderMaterials('live-materials',s,m,false); renderMaterials('maintenance-materials',s,m,true);
    const maint = s.stations.S2.state === 'FAULT' ? (m.maintenance_remaining_s > 0 ? `Repair in progress · ${fmt(m.maintenance_remaining_s)} sim-s remaining. Keep the line running.` : m.tool_ok ? 'Repair complete. Reset alarms to clear F201 and resume at RETRACT.' : 'S2 fault is latched. Repair S2, wait for completion, then Reset alarms.') : s.stations.S2.state === 'MAINT' ? `Tool change in progress · ${fmt(m.maintenance_remaining_s)} sim-s remaining.` : m.tool_change_queued ? 'Tool change queued for the next S2 WAIT boundary.' : 'Tool available. Planned changes begin after the current cycle is released.';
    $('maintenance-status').textContent = maint; $('maintenance-status').classList.toggle('faulted',s.stations.S2.state === 'FAULT');
    updateProcess(s,m);
    if (currentPage === 'live') drawChart('live-force-chart',h,'force_N',{color:'#8caa66',min:95,max:175,limits:[[105,'105','#c9d5b6'],[140,'140','#d0b36f'],[160,'160','#cb9373']],band:[105,140]});
    if (currentPage === 'trends') {
      drawChart('throughput-chart',h,'throughput',{color:'#91af6d',min:0,design:360});
      drawChart('oee-chart',h,'oee_win_pct',{color:'#88a964',min:0,max:100});
      drawChart('force-chart',h,'force_N',{color:'#8caa66',min:95,max:175,limits:[[105,'105','#c9d5b6'],[140,'140','#d0b36f'],[160,'160','#cb9373']],band:[105,140]});
      const rows = Object.entries(k.pareto).sort((a,b) => b[1] - a[1]); const max = Math.max(1,...rows.map((row) => row[1]));
      $('pareto').innerHTML = rows.length ? rows.map(([code,count]) => `<div class="pareto-row"><strong>${esc(code)}</strong><div class="progress-track"><span style="width:${count/max*100}%"></span></div><b>${count}</b></div>`).join('') : '<div class="empty-state"><strong>No rejects recorded</strong><p>Reject codes appear after inspection decisions.</p></div>';
    }
    if (!$('station-inspector').hidden) inspectStation($('station-inspector').dataset.station);
    renderControl(m.plc);
    $('profile-tag').hidden = !m.profile; $('profile-tag').textContent = m.profile || '';
    if (currentPage === 'decide' && !whatifResult) renderFork(liveFork(),'Live twin now');
    if (currentPage === 'plc') renderPlc(latest);
  }

  const PLC_IO = [
    ['I_ESTOP_OK','%MW3','in'],['I_S2_TOOL_OK','%MW4','in'],['AI_S2_FORCE','%MW5','in','N × 10'],['TWIN_WARN','%MW10','in'],['ANY_BLOCKED','%MW11','in'],
    ['M_SYS_RUN','%QX0.0','out'],['Q_LAMP_GREEN','%QX0.1','out'],['Q_LAMP_AMBER','%QX0.2','out'],['Q_LAMP_RED','%QX0.3','out'],['Q_HORN','%QX0.4','out'],
    ['F201','%QX0.5','out'],['F001','%QX0.6','out'],['F002','%QX0.7','out'],['M_ANY_FAULT','%QX1.0','out'],['M_S2_REPAIRED','%QX1.3','out'],
    ['C_IN','%QW2','out'],['C_GOOD','%QW3','out'],['C_REJECT','%QW4','out'],['BOX_FILL','%QW5','out'],['BOXES_TOTAL','%QW6','out']];
  function renderPlc(data) {
    if (!window.Ladder || !data) return;
    const v = window.Ladder.render(data,$('ladder')), plc = data.meta.plc || {};
    $('plc-source').className = `plc-source ${v.source === 'plc' ? (plc.link_ok && !plc.link_fault ? 'live' : 'down') : 'internal'}`;
    $('plc-source').innerHTML = v.source === 'plc'
      ? `${icon('plc')}<div><strong>${plc.link_ok && !plc.link_fault ? 'Live from OpenPLC Runtime' : 'OpenPLC link lost'} · ${esc(plc.endpoint)}</strong><span>Every value below is read from the PLC over Modbus TCP${plc.latency_ms != null ? ` (${fmt(plc.latency_ms)} ms round trip)` : ''}. The PLC decides run, E-stop and F201; the twin obeys.</span></div>`
      : `${icon('plc')}<div><strong>Internal control mode</strong><span>The twin is applying the same logic itself; the values shown are its equivalent state. Start with <code>launch.py --plc HOST</code> to drive this page from OpenPLC.</span></div>`;
    $('plc-io').innerHTML = table([['TAG',(r) => `<strong>${esc(r[0])}</strong>`],['ADDRESS',(r) => esc(r[1])],['DIR',(r) => r[2] === 'in' ? 'twin → PLC' : 'PLC → twin'],
      ['VALUE',(r) => { const x = v[r[0]]; return typeof x === 'boolean' ? `<span class="io-bit ${x ? 'on' : ''}">${x ? '1' : '0'}</span>` : esc(x ?? '—'); }]],PLC_IO);
  }

  function renderControl(plc) {
    const tag = $('control-tag'), strip = $('plc-strip');
    tag.hidden = browserMode;
    if (!plc || plc.mode !== 'plc') { tag.textContent = 'Internal control'; tag.className = 'runtime-tag control-tag'; strip.hidden = true; return; }
    const down = !plc.link_ok || plc.link_fault, c = plc.coils || {}, n = plc.counters || {};
    tag.textContent = down ? 'OpenPLC link down' : 'OpenPLC control'; tag.className = `runtime-tag control-tag ${down ? 'down' : 'plc'}`;
    const lamp = (on,cls) => `<i class="${on ? 'on ' : ''}${cls}"></i>`;
    const check = plc.counters_consistent == null ? 'Counter check pending' : plc.counters_consistent ? 'Counters match twin' : 'Counter mismatch';
    strip.hidden = false; strip.className = `plc-strip${down ? ' down' : ''}`;
    strip.innerHTML = `<strong>${icon('plc')}OpenPLC · ${esc(plc.endpoint)}</strong><span>${down ? `Link lost · ${esc(plc.error || 'watchdog')}` : `Modbus TCP · ${fmt(plc.latency_ms)} ms`}</span><span class="plc-lamps" title="PLC tower light">${lamp(c.Q_LAMP_GREEN,'g')}${lamp(c.Q_LAMP_AMBER,'a')}${lamp(c.M_ANY_FAULT,'r')}</span><span>Run permissive <b>${c.M_SYS_RUN ? 'ON' : 'OFF'}</b></span>${['F001','F201','F002'].filter((k) => c[k]).map((k) => `<span class="plc-tag bad">${k}${k === 'F201' && c.M_S2_REPAIRED ? ' · reset allowed' : ''}</span>`).join('')}<span>PLC counters <b>${fmt(n.C_IN,0)} in · ${fmt(n.C_GOOD,0)} good · ${fmt(n.C_REJECT,0)} reject · ${fmt(n.BOXES_TOTAL,0)} boxes</b></span><span class="plc-tag ${plc.counters_consistent === false ? 'bad' : ''}">${check}</span>`;
  }

  /* ---- Decision support: the Python sandbox owns every number shown here ---- */
  let scenarioOptions = null, scenario = 'maintenance', whatifResult = null, whatifBusy = false;
  const loopSteps = () => document.querySelectorAll('#loop-steps li');
  function setStep(active) { loopSteps().forEach((el,i) => {el.classList.toggle('done',i < active); el.classList.toggle('active',i === active);}); }
  function liveFork() {
    if (!latest) return null;
    const s = latest.snapshot, k = latest.kpi;
    return {t:s.t,wear:s.stations.S2.wear,health:k.s2.health,force:s.stations.S2.force,cycles_to_fault:k.s2.cycles_to_fault,counts:s.counts,s2_state:s.stations.S2.state,active_alarms:s.alarms.map((a) => a.code)};
  }
  function renderFork(f,title) {
    if (!f) return;
    $('fork-title').textContent = title;
    const cells = [
      ['SIMULATION TIME',fmt(f.t/60),'sim-min'],['S2 TOOL HEALTH',percent(f.health),'%',f.health < .3],
      ['LAST PRESS FORCE',fmt(f.force),'N',f.force > 135],['CYCLES TO OVERLOAD',fmt(f.cycles_to_fault,0),'estimated',f.cycles_to_fault != null && f.cycles_to_fault < 60],
      ['GOOD / REJECTED',`${fmt(f.counts.good,0)} / ${fmt(f.counts.reject,0)}`,'units'],['S2 STATE · ALARMS',esc(f.s2_state),esc(f.active_alarms.join(' ') || 'none'),f.active_alarms.length > 0]];
    $('fork-grid').innerHTML = cells.map(([label,value,unit,warn]) => `<div class="${warn ? 'warn' : ''}"><span>${label}</span><b>${value}</b><small>${unit}</small></div>`).join('');
  }
  async function loadScenarios() {
    if (browserMode) {
      $('scenario-question').textContent = 'What-if analysis runs on the local engine. Start the Windows launcher and open http://127.0.0.1:8000 to use it.';
      $('run-whatif').disabled = true; return;
    }
    if (scenarioOptions || !ready) return;
    try { scenarioOptions = await engine.request('whatif/scenarios'); setupScenario(); }
    catch (error) { feedback(`Scenarios unavailable: ${error.message}`,'error'); }
  }
  function setupScenario() {
    document.querySelectorAll('.scenario-tab').forEach((el) => {const on = el.dataset.scenario === scenario; el.classList.toggle('active',on); el.setAttribute('aria-selected',String(on));});
    if (!scenarioOptions) return;
    $('scenario-question').textContent = scenarioOptions[scenario].question;
    $('cycle-controls').hidden = scenario !== 'cycle_time';
    if (scenario === 'cycle_time' && !$('cycle-preset').options.length) {
      const o = scenarioOptions.cycle_time;
      $('cycle-preset').innerHTML = o.presets.map((p,i) => `<option value="${i}">${esc(p.label)}</option>`).join('')+'<option value="custom">Custom</option>';
      $('cycle-station').innerHTML = Object.keys(o.params.steps).map((name) => `<option>${name}</option>`).join('');
      applyPreset(0);
    }
  }
  function fillSteps() {
    const steps = scenarioOptions.cycle_time.params.steps[$('cycle-station').value];
    $('cycle-step').innerHTML = Object.entries(steps).map(([step,value]) => `<option value="${esc(step)}">${esc(step)} · ${fmt(value)} s now</option>`).join('');
  }
  function applyPreset(index) {
    const p = scenarioOptions.cycle_time.presets[index]; if (!p) return;
    $('cycle-station').value = p.station; fillSteps(); $('cycle-step').value = p.step; $('cycle-value').value = p.value;
  }
  async function runWhatIf() {
    if (browserMode || !ready || whatifBusy || !scenarioOptions) return;
    const body = {scenario,horizon_s:Number($('whatif-horizon').value),replications:Number($('whatif-reps').value),params:{}};
    if (scenario === 'cycle_time') body.params = {station:$('cycle-station').value,step:$('cycle-step').value,value:Number($('cycle-value').value)};
    whatifBusy = true; document.body.classList.add('decide-busy'); $('run-whatif').disabled = true;
    setStep(1); renderFork(liveFork(),'Copied from the live twin');
    const timers = [setTimeout(() => setStep(2),300),setTimeout(() => setStep(3),700)];
    feedback(`Running ${body.replications > 1 ? `${body.replications} seeds of ` : ''}the virtual copy for ${fmt(body.horizon_s/3600,1)} sim-hours per option…`,'pending');
    try {
      const result = await engine.request('whatif','POST',body,120000);
      timers.forEach(clearTimeout); whatifResult = result;
      setStep(4); renderWhatIf(result); setTimeout(() => setStep(5),350); setTimeout(() => setStep(6),800);
      const simHours = result.horizon_s/3600*result.arms.length*result.replications;
      feedback(`Simulated ${fmt(simHours,1)} sim-hours in ${fmt(result.runtime_s)} s. The live line was not changed.`);
    } catch (error) { timers.forEach(clearTimeout); setStep(0); feedback(`What-if failed: ${error.message}`,'error'); }
    finally { whatifBusy = false; document.body.classList.remove('decide-busy'); $('run-whatif').disabled = !ready; }
  }
  function cell(value,unit,reps) {
    if (value == null) return '—';
    if (unit === '%') return `${percent(value)} %`;
    if (unit === 's') return `${fmt(value,0)} s`;
    if (unit === 'units/h') return `${fmt(value,0)} /h`;
    return fmt(value,reps > 1 ? 1 : 0);
  }
  function deltaText(delta,unit,better,reps) {
    if (delta == null) return '';
    const tiny = Math.abs(delta) < (unit === '%' ? .0005 : unit === 's' ? .5 : .05);
    const good = (delta > 0) === (better === 'higher');
    const shown = unit === '%' ? `${delta > 0 ? '+' : ''}${fmt(delta*100)} pp` : `${delta > 0 ? '+' : ''}${cell(delta,unit,reps)}`;
    return `<span class="delta ${tiny ? 'same' : good ? 'better' : 'worse'}">${tiny ? 'no change' : shown}</span>`;
  }
  function renderWhatIf(r) {
    $('whatif-result').hidden = false;
    renderFork(r.fork,`Copied at ${fmt(r.fork.t/60)} sim-min`);
    const rec = r.recommendation, keep = rec.arm === r.arms[0].id;
    $('recommendation').className = `recommendation${keep ? ' keep' : ''}`;
    $('recommendation').innerHTML = `${icon(keep ? 'alert' : 'check')}<div><div class="kicker">RECOMMENDED ACTION · ${esc(r.title.toUpperCase())}</div><h3>${esc(rec.headline)}</h3><ul>${rec.reasons.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
    const hours = r.horizon_s/3600;
    $('compare-title').textContent = `KPI comparison · ${hours === 1 ? '1 sim-hour' : hours < 1 ? `${hours*60} sim-min` : `${hours} sim-hours`} after the copy${r.replications > 1 ? ` · mean of ${r.replications} seeds` : ''}`;
    const recommended = (a) => a.id === rec.arm ? 'recommended' : '';
    const head = `<tr><th>KPI</th>${r.arms.map((a) => `<th class="${recommended(a)}">${esc(a.label.toUpperCase())}${a.id === rec.arm ? ' ✓' : ''}</th>`).join('')}</tr>`;
    const rows = r.comparison.map((row) => `<tr><td>${esc(row.label)}</td>${row.values.map((v,i) => `<td class="${recommended(r.arms[i])}"><b>${cell(v,row.unit,r.replications)}</b>${i ? deltaText(row.deltas[i],row.unit,row.better,r.replications) : ''}</td>`).join('')}</tr>`);
    const extra = [
      ['Design capacity (static)',(a) => `${fmt(a.kpi.design.rate_ph,0)} /h · ${esc(a.kpi.design.bottleneck)}`],
      ['Simulated bottleneck',(a) => `${esc(a.kpi.bottleneck)} · ${percent(a.kpi.active_share[a.kpi.bottleneck])} % active`],
      ['First F201 after the copy',(a) => a.kpi.first_f201_s == null ? 'none' : `${fmt(a.kpi.first_f201_s/60)} sim-min`]
    ].map(([label,read]) => `<tr><td>${label}</td>${r.arms.map((a) => `<td class="${recommended(a)}"><b>${read(a)}</b></td>`).join('')}</tr>`);
    $('compare-table').innerHTML = `<table><thead>${head}</thead><tbody>${rows.join('')}${extra.join('')}</tbody></table>`;
    const bar = (u,bottleneck) => {
      const run = u.RUNNING || 0, down = u.FAULT || 0, maint = u.MAINT || 0;
      return `<div class="activity-cell${bottleneck ? ' bottleneck' : ''}"><div class="activity-bar"><i class="run" style="width:${run*100}%"></i><i class="down" style="width:${down*100}%"></i><i class="maint" style="width:${maint*100}%"></i></div><small>${fmt((run+down+maint)*100,0)}%</small></div>`;
    };
    $('activity-table').innerHTML = `<table><thead><tr><th>STATION</th>${r.arms.map((a) => `<th>${esc(a.label.toUpperCase())}</th>`).join('')}</tr></thead><tbody>${['IN','S1','S2','S3','S4'].map((name) => `<tr><td>${name}</td>${r.arms.map((a) => `<td>${bar(a.kpi.utilisation[name] || {},a.kpi.bottleneck === name)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    $('whatif-assumptions').textContent = `Assumptions: ${r.assumptions.join(' ')} Activity bars: green running, orange fault, blue maintenance.`;
  }

  function renderMaterials(id,s,m,controls) {
    const labels = {hopper:'Barrel hopper',plunger:'Plungers',stopper:'Stoppers',cap:'Caps'};
    $(id).innerHTML = Object.entries(s.bins).map(([bin,amount]) => {
      const capacity = m.material_capacity[bin], fraction = amount / capacity;
      const eta = m.refills?.[bin];
      return `<div class="material"><div class="material-label"><span>${labels[bin] || esc(bin)}</span><b>${fmt(amount,0)}<small> / ${fmt(capacity,0)}</small></b></div><div class="progress-track"><span class="${fraction < .12 ? 'low' : ''}" style="width:${Math.max(0,Math.min(100,fraction*100))}%"></span></div><div class="material-note">${eta != null ? `Refill arriving · ${fmt(eta)} sim-s` : 'Stock ready'}</div>${controls ? `<button class="button" data-command="refill" data-args='${JSON.stringify({bin})}' ${!ready || requestBusy ? 'disabled' : ''}>${icon('reset')}Request refill</button>` : ''}</div>`;
    }).join('');
  }

  function drawChart(id,rows,key,options) {
    const root = $(id); const width = 670, height = 178, left = 42, right = 25, top = 10, bottom = 28;
    const usable = rows.filter((row) => row[key] != null && Number.isFinite(row[key]));
    const min = options.min ?? (usable.length ? Math.min(...usable.map((row) => row[key]))*.9 : 0);
    const max = options.max ?? Math.max(options.design || 1,...usable.map((row) => row[key]))*1.12;
    const x0 = rows[0]?.t ?? 0, x1 = Math.max(x0+1,rows.at(-1)?.t ?? 1);
    const x = (t) => left+(t-x0)/(x1-x0)*(width-left-right);
    const y = (v) => top+(max-v)/(max-min)*(height-top-bottom);
    const safeId = `${id}-clip`; const areaId = `${id}-area`;
    let markup = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(key)} trend against simulation time"><defs><clipPath id="${safeId}"><rect x="${left}" y="${top}" width="${width-left-right}" height="${height-top-bottom}"/></clipPath><linearGradient id="${areaId}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${options.color}" stop-opacity=".12"/><stop offset="1" stop-color="${options.color}" stop-opacity="0"/></linearGradient></defs>`;
    if (options.band) markup += `<rect x="${left}" y="${y(options.band[1])}" width="${width-left-right}" height="${y(options.band[0])-y(options.band[1])}" fill="#f4f8ee"/>`;
    for (let i = 0; i < 4; i++) {
      const v = min+(max-min)*i/3, yy = y(v);
      markup += `<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" stroke="#edf2e4" stroke-width=".8"/><text x="${left-9}" y="${yy+3}" text-anchor="end" fill="#a3b292" font-size="11">${fmt(v,0)}</text>`;
    }
    const limits = [...(options.limits || []),...(options.design ? [[options.design,'360 · design','#c4d4ad']] : [])];
    for (const [value,label,color] of limits) markup += `<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" stroke="${color}" stroke-width=".8" stroke-dasharray="4 5"/><text x="${width-right-3}" y="${y(value)-4}" text-anchor="end" fill="${color}" font-size="10">${esc(label)}</text>`;
    let path = '', segment = [], segments = [];
    for (const row of rows) {
      if (row[key] == null || !Number.isFinite(row[key])) { if (segment.length) segments.push(segment); segment = []; continue; }
      segment.push([x(row.t),y(row[key]),row]);
    }
    if (segment.length) segments.push(segment);
    for (const points of segments) {
      path = points.map(([xx,yy],i) => `${i ? 'L' : 'M'}${xx.toFixed(2)},${yy.toFixed(2)}`).join(' ');
      const first = points[0], last = points.at(-1);
      markup += `<g clip-path="url(#${safeId})"><path d="${path} L${last[0]},${height-bottom} L${first[0]},${height-bottom}Z" fill="url(#${areaId})"/><path d="${path}" fill="none" stroke="${options.color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></g>`;
    }
    if (!usable.length) markup += `<text x="${width/2}" y="${height/2}" text-anchor="middle" fill="#a8b795" font-size="10">Collecting production data</text>`;
    for (let i = 0; i < 5; i++) {
      const t = x0+(x1-x0)*i/4;
      markup += `<text x="${x(t)}" y="${height-9}" text-anchor="middle" fill="#a9b897" font-size="11">${fmt(t/60,1)} m</text>`;
    }
    markup += '</svg>'; root.innerHTML = markup;
  }

  const stationX = {IN:90,S1:320,S2:550,S3:780,S4:1010,OUT:1240};
  const bufferX = {B1:205,B2:435,B3:665,B4:895};
  const stationNames = {IN:['MATERIAL INPUT','Load & identify'],S1:['PRINT & CURE','Barrel printing'],S2:['PRESS & INSERT','Plunger assembly'],S3:['CAP & MARK','Cap + laser ID'],S4:['INSPECTION','Vision + leak test'],OUT:['PACKING','Unload & box']};
  let processSnapshot = null, processMeta = null;
  const palletDisplay = new Map();

  function machineDrawing(name) {
    const syringe = `<rect class="syringe-body" x="-7" y="99" width="14" height="39" rx="3"/><path class="syringe-lines" d="M-11 101h22M0 92v9M-6 118h5m-5 6h5m-5 6h5M0 138v10M-8 92h16"/>`;
    if (name === 'IN') return `<g class="machine-lines"><path d="M-47 91h31v45h-31zM-40 84h17M-43 101h23m-23 8h23m-23 8h23M25 80v27H2v16M25 89h19v50H27"/><circle cx="25" cy="81" r="5"/></g>${syringe}<path class="machine-lines" d="M-48 147h99M-35 152v6m70-6v6"/>`;
    if (name === 'S1') return `<g class="machine-lines"><path d="M-46 146V89h92v57M-38 100h-13v36h13M38 100h13v36H38M-33 142h66M-31 90v-9h62v9M-20 106h10m-10 5h10M22 113v18M19 117h6m-6 7h6"/></g>${syringe}<rect class="machine-highlight" x="-25" y="83" width="50" height="9" rx="2"/><path class="machine-lines" d="M-43 154h86"/>`;
    if (name === 'S2') return `<g class="machine-lines"><path d="M-44 149V89h88v60M-32 89V78h64v11M-24 143h48M-39 99h-11v34h11M39 99h11v34H39M-45 157h90"/></g><rect class="machine-highlight" x="-22" y="80" width="44" height="11" rx="2"/><path class="machine-lines press-head" d="M0 91v14M-12 105h24"/>${syringe}`;
    if (name === 'S3') return `<g class="machine-lines"><path d="M-44 148V95h88v53M-28 95V81h56v14M-40 153h80M32 102h19v29H32M-34 105h9m-9 6h9M22 86v12"/></g>${syringe}<rect class="machine-highlight" x="-9" y="95" width="18" height="10" rx="2"/><path class="machine-lines" d="m29 105-12 13m12-7-7 7"/>`;
    if (name === 'S4') return `<g class="machine-lines"><path d="M-46 148V89h92v59M-27 88V80h54v8M-41 153h82M-35 105h11v24h-11zM24 109h20v17H24M32 118h5"/><circle cx="0" cy="86" r="5"/></g>${syringe}<path class="machine-lines" d="m-6 93-4 4m16-4 4 4M-5 145h10"/>`;
    return `<g class="machine-lines"><path d="M-49 143V94h98v49M-43 149h86M-17 91v-13h34v13M-45 108h16m-16 6h16m-16 6h16M29 109h15m-15 6h15"/><path d="m-16 118 16-8 16 8v22l-16 8-16-8v-22Zm0 0 16 8 16-8M0 126v22"/></g><path class="machine-highlight" d="m-16 118 16-8 16 8-16 8Z"/>`;
  }
  function buildProcess() {
    let out = `<defs><pattern id="belt-pattern" width="12" height="12" patternUnits="userSpaceOnUse"><path d="M0 0v12" stroke="#d6e0cb" stroke-width="1"/></pattern></defs><rect x="20" y="213" width="1300" height="33" rx="15" fill="#eff3e7" stroke="#dbe6ce"/><rect x="33" y="222" width="1272" height="15" rx="7" fill="url(#belt-pattern)"/><path d="M1240 252V306H90V252" stroke="#e1e9d6" stroke-width="8" fill="none"/><path d="M1240 252V306H90V252" stroke="#cfddc0" stroke-width="1" fill="none" stroke-dasharray="3 5"/><text x="650" y="331" text-anchor="middle" fill="#adbda0" font-size="8" letter-spacing="1.4">EMPTY PALLET RETURN · 10 SIM-SECONDS</text><path d="m618 300-7 6 7 6m-329-12-7 6 7 6" fill="none" stroke="#b8cba6" stroke-width="1.3"/><text x="40" y="331" fill="#a4b795" font-size="9">EMPTY PALLETS AVAILABLE <tspan id="svg-empty" font-weight="650">10</tspan></text>`;
    Object.entries(stationX).forEach(([name,x]) => {
      const labels = stationNames[name];
      out += `<g id="station-${name}" class="process-svg-station station-stopped" transform="translate(${x},0)" role="button" tabindex="0" aria-label="Inspect station ${name}"><text class="process-station-name" x="0" y="20" text-anchor="middle">${esc(name)} · ${labels[0]}</text><text class="process-station-title" x="0" y="36" text-anchor="middle">${labels[1]}</text><rect class="machine-shell" x="-73" y="55" width="146" height="134" rx="10"/><rect class="machine-interior" x="-61" y="68" width="122" height="92" rx="6"/>${machineDrawing(name)}<circle class="machine-lamp" cx="-51" cy="174" r="3"/><text id="station-state-${name}" class="process-svg-state" x="-42" y="177">STOPPED</text><rect class="process-progress-bg" x="-60" y="195" width="120" height="3" rx="1.5"/><rect id="station-progress-${name}" class="process-progress-fill" x="-60" y="195" width="0" height="3" rx="1.5"/><text id="station-step-${name}" class="process-step" x="0" y="264" text-anchor="middle">WAIT</text><text id="station-part-${name}" class="process-serial" x="0" y="278" text-anchor="middle">No part</text><text id="station-cycles-${name}" class="process-cycles" x="0" y="293" text-anchor="middle">0 cycles</text></g>`;
    });
    Object.entries(bufferX).forEach(([name,x]) => {
      out += `<g transform="translate(${x},0)"><text x="0" y="179" text-anchor="middle" fill="#a4b991" font-size="9">${name}</text><rect x="-27" y="208" width="54" height="41" rx="8" fill="#f7faf1" stroke="#e1ead5"/><rect id="buffer-slot-${name}-0" x="-21" y="217" width="18" height="21" rx="4" fill="#edf3e3" stroke="#dce8d0"/><rect id="buffer-slot-${name}-1" x="3" y="217" width="18" height="21" rx="4" fill="#edf3e3" stroke="#dce8d0"/><text id="buffer-label-${name}" x="0" y="268" text-anchor="middle" fill="#a2b68a" font-size="8">0 / 2</text><text id="buffer-reserved-${name}" x="0" y="283" text-anchor="middle" fill="#b8c5a7" font-size="7"></text></g>`;
    });
    out += `<g id="pallet-layer">${Array.from({length:10},(_,i) => `<g id="pallet-${i+1}" class="pallet-marker" opacity="0"><rect x="-10" y="-11" width="20" height="22" rx="4" fill="#a5bc82" stroke="#94aa6d" stroke-width=".8"/><text y="4">${i+1}</text></g>`).join('')}</g>`;
    $('process-svg').innerHTML = out;
    Object.keys(stationX).forEach((name) => {
      $(`station-${name}`).addEventListener('click',() => inspectStation(name));
      $(`station-${name}`).addEventListener('keydown',(event) => {if (['Enter',' '].includes(event.key)) {event.preventDefault(); inspectStation(name);}});
    });
  }
  function inspectStation(name) {
    if (!latest || !name) return;
    const st = latest.snapshot.stations[name], progress = latest.meta.station_progress?.[name];
    $('station-inspector').hidden = false; $('station-inspector').dataset.station = name;
    $('station-inspector').innerHTML = `<strong>${esc(name)} · ${esc(st.state)}</strong><span>${esc(st.reason || st.step)}</span><span>Part: <b>${esc(st.part || '—')}</b></span><span>Cycles: <b>${fmt(st.cycles,0)}</b></span><span>Last cycle: <b>${fmt(st.last_ct)} s</b></span>${progress?.duration ? `<span>Step: <b>${fmt(progress.elapsed)} / ${fmt(progress.duration)} s</b></span>` : ''}<button aria-label="Close station details" id="close-inspector">✕</button>`;
    $('close-inspector').onclick = () => { $('station-inspector').hidden = true; };
  }
  function updateProcess(s,m) {
    processSnapshot = s; processMeta = m;
    for (const [name,st] of Object.entries(s.stations)) {
      const stateClass = {RUNNING:'processing',FAULT:'fault',MAINT:'maintenance',BLOCKED:'blocked',STARVED:'starved',STOPPED:'stopped'}[st.state] || 'stopped';
      $(`station-${name}`).setAttribute('class',`process-svg-station station-${stateClass}`);
      $(`station-state-${name}`).textContent = st.state === 'RUNNING' ? 'PROCESSING' : st.state === 'MAINT' ? 'MAINTENANCE' : st.state;
      $(`station-step-${name}`).textContent = st.step; $(`station-part-${name}`).textContent = st.part ? st.part.replace('SYR-B07-','#') : 'No part';
      $(`station-cycles-${name}`).textContent = `${fmt(st.cycles,0)} cycles`;
      const p = m.station_progress?.[name]?.progress ?? 0;
      $(`station-progress-${name}`).setAttribute('width',Math.max(0,Math.min(1,p))*120);
    }
    for (const [name,serials] of Object.entries(s.buffers)) {
      const capacity = m.buffer_capacity?.[name] ?? 2;
      $(`buffer-label-${name}`).textContent = `${serials.length} / ${capacity}`;
      const reserved = (m.transfers || []).filter((tr) => tr.destination === name).length;
      $(`buffer-reserved-${name}`).textContent = reserved ? `+${reserved} reserved` : '';
    }
    $('svg-empty').textContent = m.empty_pallets;
    $('transfer-count').textContent = `${m.transfers?.length ?? 0} pallets in transit`;
  }
  function locationFor(name,pid) {
    if (stationX[name] != null) return {x:stationX[name],y:228};
    if (bufferX[name] != null) {
      const serial = processMeta?.pallets?.[pid], serials = processSnapshot?.buffers?.[name] || [];
      const index = serials.indexOf(serial);
      return {x:bufferX[name]+(index === 1 ? 12 : -12),y:228};
    }
    return {x:90,y:306};
  }
  function transferPosition(tr,elapsed) {
    const elapsedSim = processSnapshot.run && connected && !reduceMotion ? Math.min(.65,elapsed)*processSnapshot.speed : 0;
    const progress = Math.max(0,Math.min(1,1-(tr.remaining-elapsedSim)/tr.total));
    const start = locationFor(tr.source,tr.pallet);
    if (tr.destination === 'RETURN') {
      const vertical = 78, horizontal = Math.abs(start.x-90), total = vertical+horizontal+54;
      let d = progress*total;
      if (d < vertical) return {x:start.x,y:228+d}; d -= vertical;
      if (d < horizontal) return {x:start.x-d,y:306}; d -= horizontal;
      return {x:90,y:306-d};
    }
    const end = locationFor(tr.destination,tr.pallet);
    if (bufferX[tr.destination] != null) {
      const inbound = (processMeta.transfers || []).filter((item) => item.destination === tr.destination);
      const occupied = processSnapshot.buffers[tr.destination]?.length || 0;
      const index = Math.min(1,occupied+inbound.findIndex((item) => item.pallet === tr.pallet));
      end.x = bufferX[tr.destination]+(index ? 12 : -12);
    }
    return {x:start.x+(end.x-start.x)*progress,y:start.y+(end.y-start.y)*progress};
  }
  function animate(now) {
    if (processSnapshot && processMeta && currentPage === 'live') {
      const positions = new Map();
      const reverse = new Map(Object.entries(processMeta.pallets || {}).filter(([,serial]) => serial != null).map(([pid,serial]) => [serial,Number(pid)]));
      for (const [name,info] of Object.entries(processMeta.station_progress || {})) if (info.pallet != null) positions.set(Number(info.pallet),locationFor(name,info.pallet));
      for (const [name,serials] of Object.entries(processSnapshot.buffers)) for (const serial of serials) if (reverse.has(serial)) positions.set(reverse.get(serial),locationFor(name,reverse.get(serial)));
      const elapsed = Math.max(0,(now-lastSnapshotAt)/1000);
      for (const tr of processMeta.transfers || []) positions.set(tr.pallet,transferPosition(tr,elapsed));
      for (let pid = 1; pid <= 10; pid++) {
        const el = $(`pallet-${pid}`), pos = positions.get(pid), previous = palletDisplay.get(pid);
        if (!pos) { el.setAttribute('opacity','0'); palletDisplay.delete(pid); continue; }
        // Smooth display updates only; position targets and membership come from Python.
        const blend = reduceMotion || !previous || !connected || !processSnapshot.run ? 1 : .3;
        const rendered = previous ? {x:previous.x+(pos.x-previous.x)*blend,y:previous.y+(pos.y-previous.y)*blend,target:pos} : {...pos,target:pos};
        palletDisplay.set(pid,rendered); el.setAttribute('transform',`translate(${rendered.x.toFixed(2)},${rendered.y.toFixed(2)})`); el.setAttribute('opacity','1');
        const serial = processMeta.pallets?.[pid]; el.setAttribute('aria-label',`Pallet ${pid}${serial ? ` · ${serial}` : ' · empty'}`);
      }
    }
    requestAnimationFrame(animate);
  }

  function table(columns,rows) {
    if (!rows.length) return '<div class="table-empty">No records in this run yet.</div>';
    return `<table><thead><tr>${columns.map(([label]) => `<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map(([,read,wrap]) => `<td${wrap ? ' class="wrap"' : ''}>${read(row)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  async function loadPageRecords(force = false) {
    if (!ready || logsBusy || (!force && performance.now()-lastLogAt < 1800)) return;
    logsBusy = true; lastLogAt = performance.now();
    try {
      if (currentPage === 'alarms') {
        const [alarms,commands,events] = await Promise.all([engine.read('alarms?limit=100'),engine.read('commands?limit=100'),engine.read('events?limit=50')]);
        auditRows = commands;
        $('alarm-history').innerHTML = table([['CODE',(r) => `<strong>${esc(r.code)}</strong>`],['SEVERITY',(r) => `<span class="severity ${esc(r.sev)}">${esc(r.sev)}</span>`],['STATION',(r) => esc(r.station || 'Cell')],['RAISED · SIM-S',(r) => fmt(r.t_raised)],['CLEARED · SIM-S',(r) => r.t_cleared == null ? '<span class="severity">ACTIVE</span>' : fmt(r.t_cleared)],['DETAIL',(r) => esc(r.text)+(r.injected ? ' · Injected by operator' : ''),true]],alarms);
        $('command-history').innerHTML = table([['SIM-S',(r) => fmt(r.t)],['OPERATOR',(r) => esc(r.user)],['COMMAND',(r) => esc(r.cmd)],['ARGUMENTS',(r) => esc(JSON.stringify(r.args))],['RESULT',(r) => esc(r.result),true],['WALL TIME',(r) => esc(r.wall)]],commands);
        $('event-history').innerHTML = table([['SIM-S',(r) => fmt(r.t)],['TYPE',(r) => esc(r.type)],['STATION',(r) => esc(r.station || '—')],['SERIAL',(r) => esc(r.serial || '—')],['DETAIL',(r) => esc(JSON.stringify(Object.fromEntries(Object.entries(r).filter(([key]) => !['t','type','station','serial'].includes(key))))),true]],events);
      } else if (currentPage === 'trace') {
        recentParts = await engine.read('parts?limit=30');
        $('recent-parts').innerHTML = table([['SERIAL',(r) => `<button class="serial-link" data-serial="${esc(r.serial)}">${esc(r.serial)}</button>`],['STATUS',(r) => `<span class="severity ${esc(r.status)}">${esc(r.status)}</span>`],['LOADED · SIM-S',(r) => fmt(r.t_in)],['COMPLETED · SIM-S',(r) => fmt(r.t_out)],['REJECT CODES',(r) => esc(r.reject_codes.join(', ') || '—')]],recentParts);
        if (tracePart) {
          const newPart = recentParts.find((p) => p.serial === tracePart.serial);
          if (newPart) showPart(newPart);
        }
      }
    } catch (error) { if (connected) feedback(`Records unavailable: ${error.message}`,'error'); }
    finally {logsBusy = false;}
  }
  async function findPart(serial) {
    if (!serial) { feedback('Enter a serial to look up.','error'); return; }
    if (!ready) { feedback('Connect to the engine before looking up a part.','error'); return; }
    try { showPart(await engine.read(`parts/${encodeURIComponent(serial.trim().toUpperCase())}`)); }
    catch (error) { feedback(error.rejected ? error.message : `Part lookup failed: ${error.message}`,'error'); }
  }
  function showPart(part) {
    tracePart = part; $('trace-detail').hidden = false;
    const measurements = [
      ['Press force',fmt(part.meas.force_N)+' N','105–140 N quality window'],
      ['Leak rate',fmt(part.meas.leak_Pa_s)+' Pa/s','5 Pa/s limit'],
      ['Print offset',fmt(part.meas.print_offset_mm,3)+' mm','Barrel print measurement'],
      ['Cap & mark',`${part.meas.cap_ok == null ? '—' : part.meas.cap_ok ? 'Cap OK' : 'Cap failed'} · ${part.meas.mark_grade ?? '—'}`,'Laser mark grade A–D']
    ];
    $('trace-detail').innerHTML = `<article class="panel"><div class="trace-heading"><div><span class="panel-kicker">PART RECORD</span><h2>${esc(part.serial)}<span class="severity ${esc(part.status)}">${esc(part.status)}</span></h2><p>Loaded ${fmt(part.t_in)} sim-s <span class="bullet">·</span> Completed ${fmt(part.t_out)} sim-s <span class="bullet">·</span> Reject codes: ${esc(part.reject_codes.join(', ') || 'None')}</p></div><button id="export-part" class="button">${icon('download')}Export JSON</button></div><div class="trace-measurements">${measurements.map(([label,value,note]) => `<div class="trace-measurement"><span>${label}</span><b>${esc(value)}</b><small>${note}</small></div>`).join('')}</div><div class="trace-timeline"><h3>Process journey · ${part.events.length} events</h3>${part.events.map((event) => `<div class="timeline-row"><span>${fmt(event.t)} s</span><strong>${esc(event.station || 'CELL')}</strong><p>${esc(event.event || event.action || event.type)}${event.step ? ' · '+esc(event.step) : ''}${event.injected ? ' · OPERATOR INJECTED' : ''}${event.force_N != null ? ' · '+fmt(event.force_N)+' N' : ''}</p></div>`).join('')}</div></article>`;
    $('export-part').onclick = () => download(JSON.stringify(tracePart,null,2),`${tracePart.serial}.json`,'application/json');
  }
  function download(value,name,type) {
    const url = URL.createObjectURL(new Blob([value],{type})), link = document.createElement('a');
    link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  function csv(rows,columns) {
    const quote = (value) => `"${String(value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : value).replaceAll('"','""')}"`;
    return [columns.map(quote).join(','),...rows.map((row) => columns.map((col) => quote(row[col])).join(','))].join('\r\n');
  }

  document.addEventListener('click',(event) => {
    const commandButton = event.target.closest('[data-command]');
    if (commandButton && !commandButton.disabled) sendCommand(commandButton.dataset.command,JSON.parse(commandButton.dataset.args || '{}'));
    const nav = event.target.closest('[data-page],[data-navigate]');
    if (nav) navigate(nav.dataset.page || nav.dataset.navigate);
    const part = event.target.closest('[data-serial]');
    if (part) findPart(part.dataset.serial);
  });
  $('estop').onclick = () => sendCommand('estop',{active:!latest?.meta.estop_active});
  $('speed').onchange = () => sendCommand('set_speed',{x:Number($('speed').value)});
  $('retry').onclick = boot;
  document.querySelectorAll('.scenario-tab').forEach((el) => { el.onclick = () => {scenario = el.dataset.scenario; setupScenario();}; });
  $('cycle-preset').onchange = () => applyPreset(Number($('cycle-preset').value));
  $('cycle-station').onchange = () => {fillSteps(); $('cycle-preset').value = 'custom';};
  $('cycle-step').onchange = $('cycle-value').oninput = () => {$('cycle-preset').value = 'custom';};
  $('run-whatif').onclick = runWhatIf;
  $('export-whatif').onclick = () => {if (whatifResult) download(JSON.stringify(whatifResult,null,2),`SyringeTwin-whatif-${whatifResult.scenario}.json`,'application/json');};
  $('operator').oninput = () => {
    document.querySelector('.operator-field').classList.remove('invalid');
    try {localStorage.setItem(operatorStorage,$('operator').value);} catch (_) {/* Browser storage may be unavailable. */}
  };
  try { $('operator').value = localStorage.getItem(operatorStorage) || ''; } catch (_) {/* Operator can still type a name. */}
  $('trace-form').onsubmit = (event) => {event.preventDefault(); findPart($('serial-search').value);};
  $('export-trends').onclick = () => {if (latest) download(csv(latest.history || [],['t','throughput','force_N','oee_pct','oee_win_pct']),'SyringeTwin-trends.csv','text/csv');};
  $('export-audit').onclick = () => download(csv(auditRows,['t','wall','user','cmd','args','result']),'SyringeTwin-audit.csv','text/csv');
  window.addEventListener('hashchange',() => navigate(location.hash.slice(1)));
  window.addEventListener('beforeunload',() => { if (engine instanceof BrowserEngine) engine.close(); });
  buildProcess(); navigate(currentPage); requestAnimationFrame(animate); boot();
})();
