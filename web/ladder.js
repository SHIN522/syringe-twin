/* Live ladder view of plc/openplc/syringetwin.st. Each rung is the ladder form of one ST statement:
   AND = contacts in series, OR = parallel branch, NOT = normally-closed contact, R_TRIG = |P| contact,
   ':= TRUE / FALSE' latches = (S) / (R) coils. Values come from OpenPLC over Modbus (PLC mode) or,
   in internal mode, from the twin's own state through the same logic. Display only: never writes. */
(() => {
  'use strict';
  const C = (tag, label) => ({k:'no', tag, label});          // normally-open contact
  const N = (tag, label) => ({k:'nc', tag, label});          // normally-closed contact
  const E = (tag, label) => ({k:'edge', tag, label});        // rising-edge contact |P|
  const CMP = (tag, op, ref, label) => ({k:'cmp', tag, op, ref, label});
  const S = (...items) => ({k:'ser', items});
  const P = (...items) => ({k:'par', items});
  const coil = (tag, type = '') => ({k:'coil', tag, type});
  const block = (name, lines, q) => ({k:'block', name, lines, q});

  const RUNGS = [
    {group:'P1 · Master control', id:'P1-R1', title:'Run seal-in: only an E-stop or a lost link stops the line',
     st:'M_SYS_RUN := (START_RE OR M_SYS_RUN) AND NOT STOP_B\n             AND NOT F001 AND NOT F002;',
     net:S(P(E('START_B','START'), C('M_SYS_RUN')), N('STOP_B','STOP'), N('F001'), N('F002')), out:[coil('M_SYS_RUN')]},
    {group:'P1 · Master control', id:'P1-R2a', title:'E-stop chain open → latch F001',
     st:'IF NOT ESTOP_OK THEN F001 := TRUE; END_IF;', net:N('ESTOP_OK','I_ESTOP_OK'), out:[coil('F001','S')]},
    {group:'P1 · Master control', id:'P1-R2b', title:'Reset clears F001 only with the E-stop released',
     st:'IF RESET_RE AND ESTOP_OK THEN F001 := FALSE; END_IF;', net:S(E('RESET_B','RESET'), C('ESTOP_OK','I_ESTOP_OK')), out:[coil('F001','R')]},
    {group:'P1 · Master control', id:'P1-R4', title:'Any fault → flashing red lamp and horn',
     st:'Q_LAMP_RED := M_ANY_FAULT AND BLINK;\nQ_HORN := M_ANY_FAULT;', net:S(C('M_ANY_FAULT'), C('BLINK')), out:[coil('Q_LAMP_RED'), coil('Q_HORN')]},
    {group:'P1 · Master control', id:'P1-R5', title:'Warning or blocked station, no fault → amber lamp',
     st:'Q_LAMP_AMBER := NOT M_ANY_FAULT AND (TWIN_WARN OR ANY_BLOCKED);',
     net:S(N('M_ANY_FAULT'), P(C('TWIN_WARN'), C('ANY_BLOCKED'))), out:[coil('Q_LAMP_AMBER')]},
    {group:'P1 · Master control', id:'P1-R6', title:'Running with no fault or warning → green lamp',
     st:'Q_LAMP_GREEN := M_SYS_RUN AND NOT M_ANY_FAULT AND NOT Q_LAMP_AMBER;',
     net:S(C('M_SYS_RUN'), N('M_ANY_FAULT'), N('Q_LAMP_AMBER')), out:[coil('Q_LAMP_GREEN')]},
    {group:'P5 · S2 force monitoring', id:'P5-R1', title:'New press sample above 160.0 N → latch F201',
     st:'IF NEW_PRESS AND (AI_S2_FORCE > 1600) THEN\n  F201 := TRUE; M_S2_REPAIRED := FALSE;\nEND_IF;',
     net:S(C('NEW_PRESS'), CMP('AI_S2_FORCE','>',1600,'AI_S2_FORCE')), out:[coil('F201','S'), coil('M_S2_REPAIRED','R')]},
    {group:'P5 · S2 force monitoring', id:'P5-R2', title:'Operator test injection → latch F201, marked injected',
     st:'IF INJECT_RE THEN F201 := TRUE; F201_INJECTED := TRUE; END_IF;',
     net:E('INJECT_B','INJECT'), out:[coil('F201','S'), coil('F201_INJECTED','S')]},
    {group:'P5 · S2 force monitoring', id:'P5-R3', title:'Echo the evaluated sample: the twin may start INSERT',
     st:'IF NEW_PRESS THEN S2_VERDICT_SEQ := S2_PRESS_SEQ; END_IF;',
     net:C('NEW_PRESS'), out:[block('MOVE', ['IN  S2_PRESS_SEQ', 'OUT S2_VERDICT_SEQ'], 'VERDICT_SEQ')]},
    {group:'P8 · Alarms and recovery', id:'P8-R1', title:'Tool OK returns while F201 is latched → repair acknowledged',
     st:'IF F201 AND TOOL_OK_RE THEN M_S2_REPAIRED := TRUE; END_IF;',
     net:S(C('F201'), E('TOOL_OK','I_S2_TOOL_OK')), out:[coil('M_S2_REPAIRED','S')]},
    {group:'P8 · Alarms and recovery', id:'P8-R2', title:'Reset clears F201 only after a completed repair',
     st:'IF RESET_RE AND F201 AND M_S2_REPAIRED AND TOOL_OK THEN\n  F201 := FALSE; M_S2_REPAIRED := FALSE; F201_INJECTED := FALSE;\nEND_IF;',
     net:S(E('RESET_B','RESET'), C('F201'), C('M_S2_REPAIRED'), C('TOOL_OK','I_S2_TOOL_OK')),
     out:[coil('F201','R'), coil('M_S2_REPAIRED','R'), coil('F201_INJECTED','R')]},
    {group:'P8 · Alarms and recovery', id:'P8-R3', title:'Twin heartbeat silent for 1 s → link fault F002',
     st:'T_WD(IN := LINK_SEEN AND NOT HB_CHANGED, PT := T#1s);\nIF T_WD.Q THEN F002 := TRUE; END_IF;',
     net:S(C('LINK_SEEN'), N('HB_CHANGED')), out:[block('TON T_WD', ['PT  T#1s'], 'F002'), coil('F002','S')]},
    {group:'P8 · Alarms and recovery', id:'P8-R5', title:'Fault summary',
     st:'M_ANY_FAULT := F001 OR F201 OR F002;', net:P(C('F001'), C('F201'), C('F002')), out:[coil('M_ANY_FAULT')]},
    {group:'P9 · Counters', id:'P9-R2', title:'Count good units',
     st:'C_GOOD(CU := NEW_GOOD, R := FALSE, PV := 32000);', net:C('NEW_GOOD'), out:[block('CTU C_GOOD', ['PV  32000', 'CV  {C_GOOD}'], null)]},
    {group:'P9 · Counters', id:'P9-R4', title:'Box of ten: the counter wraps and a box is completed',
     st:'C_BOX(CU := NEW_GOOD, PV := 10);\nIF C_BOX.Q THEN BOXES_TOTAL := BOXES_TOTAL + 1; ... END_IF;',
     net:C('NEW_GOOD'), out:[block('CTU C_BOX', ['PV  10', 'CV  {BOX_FILL}', 'BOXES {BOXES_TOTAL}'], null)]},
    {group:'P2 · Transfer interlock', id:'P2-R1', title:'S2 may release its pallet: done, B3 has room, running, no fault',
     st:'S2_RELEASE_PERMIT := S2_DONE AND B3_ROOM AND M_SYS_RUN AND NOT F201;',
     net:S(C('S2_DONE'), C('B3_ROOM'), C('M_SYS_RUN'), N('F201')), out:[coil('S2_RELEASE_PERMIT')]}
  ];

  /* ---- values: real PLC (Modbus) or the twin's equivalent state ---- */
  function values(live) {
    const s = live.snapshot, m = live.meta, plc = m.plc || {mode:'internal'};
    const blink = Math.floor(Date.now() / 500) % 2 === 0;
    const st2 = s.stations.S2, active = s.alarms.map((a) => a.code);
    const blocked = Object.values(s.stations).some((st) => st.state === 'BLOCKED');
    const s2done = st2.part != null && st2.step === 'RELEASE';
    if (plc.mode === 'plc') {
      const c = plc.coils || {}, i = plc.inputs || {}, n = plc.counters || {};
      return {source:'plc', BLINK:blink, ...c, ...n,
        ESTOP_OK:!!i.I_ESTOP_OK, TOOL_OK:!!i.I_S2_TOOL_OK, AI_S2_FORCE:i.AI_S2_FORCE ?? 0,
        TWIN_WARN:!!i.TWIN_WARN, ANY_BLOCKED:!!i.ANY_BLOCKED, STOP_B:!!i.CMD_STOP, START_B:!!i.CMD_START,
        RESET_B:!!i.CMD_RESET, INJECT_B:!!i.CMD_INJECT_F201, S2_DONE:!!i.S2_DONE, B3_ROOM:!!i.B3_ROOM,
        NEW_PRESS:false, NEW_GOOD:false, LINK_SEEN:!!plc.link_ok, HB_CHANGED:!!plc.link_ok && !plc.link_fault,
        VERDICT_SEQ:plc.verdict_seq, inputs:i};
    }
    const F001 = !!m.estop_latched, F201 = active.includes('F201'), F002 = active.includes('F002');
    const anyFault = F001 || F201 || F002;
    const warn = s.alarms.some((a) => a.sev === 'WARN');
    const amber = !anyFault && (warn || blocked);
    return {source:'internal', BLINK:blink, M_SYS_RUN:s.run, F001, F201, F002, M_ANY_FAULT:anyFault,
      ESTOP_OK:!m.estop_active, TOOL_OK:!!m.tool_ok, AI_S2_FORCE:Math.round((st2.force ?? 0) * 10),
      TWIN_WARN:warn, ANY_BLOCKED:blocked, STOP_B:false, START_B:false, RESET_B:false, INJECT_B:false,
      Q_LAMP_RED:anyFault && blink, Q_HORN:anyFault, Q_LAMP_AMBER:amber, Q_LAMP_GREEN:s.run && !anyFault && !amber,
      M_S2_REPAIRED:F201 && !!m.tool_ok, F201_INJECTED:false, S2_DONE:s2done, B3_ROOM:(s.buffers.B3 || []).length < 2,
      S2_RELEASE_PERMIT:s2done && (s.buffers.B3 || []).length < 2 && s.run && !F201,
      NEW_PRESS:false, NEW_GOOD:false, LINK_SEEN:false, HB_CHANGED:true,
      C_IN:s.counts.in, C_GOOD:s.counts.good, C_REJECT:s.counts.reject, BOX_FILL:s.counts.good % 10, BOXES_TOTAL:s.counts.boxes};
  }

  /* ---- evaluation: does power pass through this node? ---- */
  function passes(node, v) {
    if (node.k === 'no' || node.k === 'edge') return !!v[node.tag];
    if (node.k === 'nc') return !v[node.tag];
    if (node.k === 'cmp') return node.op === '>' ? (v[node.tag] ?? 0) > node.ref : (v[node.tag] ?? 0) < node.ref;
    if (node.k === 'ser') return node.items.every((it) => passes(it, v));
    if (node.k === 'par') return node.items.some((it) => passes(it, v));
    return false;
  }

  /* ---- layout + drawing (SVG) ---- */
  const CW = 84, RH = 58, ON = '#22a35a', OFF = '#9aa79a', INK = '#34463b';
  const esc = (t) => String(t).replace(/[&<>"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
  const size = (n) => n.k === 'ser' ? n.items.map(size).reduce((a, b) => ({w:a.w + b.w, h:Math.max(a.h, b.h)}), {w:0, h:0})
    : n.k === 'par' ? n.items.map(size).reduce((a, b) => ({w:Math.max(a.w, b.w), h:a.h + b.h}), {w:0, h:0})
    : {w:n.k === 'cmp' ? CW + 52 : CW, h:RH};
  const wire = (x1, y1, x2, y2, on) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${on ? ON : OFF}" stroke-width="${on ? 3 : 1.6}"/>`;

  function element(n, x, y, powerIn, v) {
    const mid = y + RH / 2, ok = passes(n, v), out = powerIn && ok;
    const label = n.label || n.tag;
    const value = n.k === 'cmp' ? `${v[n.tag] ?? 0} ${n.op} ${n.ref}` : (v[n.tag] ? 'TRUE' : 'FALSE');
    let g = wire(x, mid, x + 34, mid, powerIn) + wire(x + (n.k === 'cmp' ? 96 : 62), mid, x + size(n).w, mid, out);
    if (n.k === 'cmp') {
      g += `<rect x="${x + 34}" y="${mid - 15}" width="62" height="30" rx="3" fill="${ok ? '#e5f6eb' : '#fff'}" stroke="${ok ? ON : INK}" stroke-width="1.4"/>`
        + `<text x="${x + 65}" y="${mid + 4}" text-anchor="middle" font-size="11" font-weight="700" fill="${INK}">GT</text>`;
    } else {
      const fill = ok ? ON : 'none';
      g += `<line x1="${x + 38}" y1="${mid - 13}" x2="${x + 38}" y2="${mid + 13}" stroke="${ok ? ON : INK}" stroke-width="2.4"/>`
        + `<line x1="${x + 58}" y1="${mid - 13}" x2="${x + 58}" y2="${mid + 13}" stroke="${ok ? ON : INK}" stroke-width="2.4"/>`
        + `<rect x="${x + 40}" y="${mid - 11}" width="16" height="22" fill="${fill}" opacity="${ok ? 0.18 : 0}"/>`;
      if (n.k === 'nc') g += `<line x1="${x + 36}" y1="${mid + 13}" x2="${x + 60}" y2="${mid - 13}" stroke="${ok ? ON : INK}" stroke-width="1.6"/>`;
      if (n.k === 'edge') g += `<text x="${x + 48}" y="${mid + 4}" text-anchor="middle" font-size="11" font-weight="700" fill="${INK}">P</text>`;
    }
    g += `<text x="${x + (n.k === 'cmp' ? 65 : 48)}" y="${mid - 19}" text-anchor="middle" font-size="10" font-weight="600" fill="${INK}">${esc(label)}</text>`
      + `<text x="${x + (n.k === 'cmp' ? 65 : 48)}" y="${mid + 26}" text-anchor="middle" font-size="9" fill="${ok ? ON : '#7d8b80'}">${esc(value)}</text>`;
    return {g, out};
  }

  function draw(n, x, y, powerIn, v) {
    if (n.k === 'ser') {
      let g = '', p = powerIn, cx = x;
      const h = size(n).h;
      for (const it of n.items) { const r = draw(it, cx, y, p, v); g += r.g; p = r.out; cx += size(it).w; }
      return {g, out:p, h};
    }
    if (n.k === 'par') {
      const {w} = size(n);
      let g = '', cy = y, any = false;
      const mids = [];
      for (const it of n.items) {
        const r = draw(it, x, cy, powerIn, v), iw = size(it).w;
        g += r.g + wire(x + iw, cy + RH / 2, x + w, cy + RH / 2, r.out);
        mids.push(cy + RH / 2); any = any || r.out; cy += size(it).h;
      }
      g += wire(x, mids[0], x, mids.at(-1), powerIn) + wire(x + w, mids[0], x + w, mids.at(-1), any);
      return {g, out:any};
    }
    return element(n, x, y, powerIn, v);
  }

  function outputs(list, x, mid, powered, v) {
    let g = '', cx = x;
    for (const o of list) {
      if (o.k === 'block') {
        const lines = o.lines.map((t) => t.replace(/\{(\w+)\}/g, (_, tag) => v[tag] ?? '—'));
        const h = 22 + 14 * lines.length, top = mid - 15;
        g += wire(cx, mid, cx + 14, mid, powered)
          + `<rect x="${cx + 14}" y="${top}" width="128" height="${h}" rx="4" fill="${powered ? '#e5f6eb' : '#fff'}" stroke="${powered ? ON : INK}" stroke-width="1.4"/>`
          + `<text x="${cx + 78}" y="${top + 15}" text-anchor="middle" font-size="10.5" font-weight="700" fill="${INK}">${esc(o.name)}</text>`
          + lines.map((t, i) => `<text x="${cx + 22}" y="${top + 31 + 14 * i}" font-size="9.5" fill="#56685b">${esc(t)}</text>`).join('');
        cx += 142;
        if (o.q) powered = !!v[o.q];
        continue;
      }
      const on = !!v[o.tag];
      g += wire(cx, mid, cx + 16, mid, powered)
        + `<circle cx="${cx + 36}" cy="${mid}" r="15" fill="${on ? '#e5f6eb' : '#fff'}" stroke="${on ? ON : INK}" stroke-width="${on ? 2.6 : 1.6}"/>`
        + `<text x="${cx + 36}" y="${mid + 4}" text-anchor="middle" font-size="11" font-weight="700" fill="${INK}">${o.type || ''}</text>`
        + `<text x="${cx + 36}" y="${mid - 21}" text-anchor="middle" font-size="10" font-weight="600" fill="${INK}">${esc(o.tag)}</text>`
        + `<text x="${cx + 36}" y="${mid + 29}" text-anchor="middle" font-size="9" fill="${on ? ON : '#7d8b80'}">${on ? 'TRUE' : 'FALSE'}</text>`;
      cx += 80;
    }
    return {g, w:cx - x};
  }

  function rungSvg(r, v) {
    const s = size(r.net), left = 16, x0 = left + 8, mid = RH / 2 + 6;
    const net = draw(r.net, x0, 6, true, v);
    const outX = x0 + s.w + 24;
    const outs = outputs(r.out, outX, mid, net.out, v);
    const width = outX + outs.w + 30, height = s.h + 12;
    // inline style beats the dashboard's 20 px icon rule for svg elements
    return `<svg viewBox="0 0 ${width} ${height}" style="width:${width}px;height:${height}px;fill:none;stroke:none" role="img" aria-label="Ladder rung ${esc(r.id)}">`
      + `<line x1="${left}" y1="2" x2="${left}" y2="${height - 2}" stroke="${ON}" stroke-width="4"/>`
      + `<line x1="${width - 12}" y1="2" x2="${width - 12}" y2="${height - 2}" stroke="${INK}" stroke-width="4"/>`
      + wire(left, mid, x0, mid, true) + net.g + wire(x0 + s.w, mid, outX, mid, net.out) + outs.g
      + wire(outX + outs.w, mid, width - 12, mid, net.out) + '</svg>';
  }

  function render(live, root) {
    if (!live || !root) return;
    const v = values(live);
    let html = '', group = '';
    for (const r of RUNGS) {
      if (r.group !== group) { group = r.group; html += `<h3 class="ladder-group">${esc(group)}</h3>`; }
      const energised = passes(r.net, v);
      html += `<article class="ladder-rung${energised ? ' energised' : ''}"><div class="ladder-head"><b>${esc(r.id)}</b><span>${esc(r.title)}</span>`
        + `<em>${energised ? 'POWER FLOWING' : 'not energised'}</em></div><div class="ladder-body"><div class="ladder-svg">${rungSvg(r, v)}</div>`
        + `<pre class="ladder-st"><span>Structured Text</span>${esc(r.st)}</pre></div></article>`;
    }
    root.innerHTML = html;
    return v;
  }

  window.Ladder = {render, values, RUNGS};
})();
