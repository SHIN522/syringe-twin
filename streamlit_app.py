"""Live Streamlit dashboard. Run via launch.py; simulation owns its own clock."""
import json
from datetime import datetime
import pandas as pd
import streamlit as st
from dashboard_client import get, send
from dashboard_visuals import overview, trend

st.set_page_config(page_title='SyringeTwin | Live Cell',page_icon='🏭',layout='wide')
st.markdown('''<style>
.block-container {padding-top:1.7rem;padding-bottom:1.5rem;max-width:1600px;}
h1 {font-size:2rem!important;letter-spacing:-.05em;margin-bottom:0!important;}
[data-testid="stMetric"] {background:#111E32;border:1px solid #203550;border-radius:12px;padding:14px;}
[data-testid="stMetricLabel"] {color:#9BADBF;font-size:.8rem;}
[data-testid="stMetricValue"] {font-size:1.8rem;}
.st-key-estop button {background:#BE123C;color:white;border-color:#BE123C;}
.st-key-start button {background:#047857;color:white;border-color:#047857;}
.eyebrow {font-size:11px;letter-spacing:.15em;color:#38BDF8;font-weight:700;}
.cell-status {padding:12px 16px;border:1px solid #203550;background:#111E32;border-radius:12px;font-size:14px;}
</style>''',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('### SYRINGE<span style="color:#38BDF8">TWIN</span>',unsafe_allow_html=True)
    st.caption('GROUP 07 · ASSEMBLY CELL')
    page = st.radio('Workspace',['Live cell','Trends','Alarms & audit','Traceability','Maintenance'],label_visibility='collapsed')
    st.divider()
    user = st.text_input('Operator name',value='Aryan',max_chars=80)
    speed = st.select_slider('Simulation speed',options=[1,2,5,10,50],value=10,format_func=lambda x:f'{x}×')
    if st.button('Apply speed',width='stretch'):
        ok,msg = send('set_speed',{'x':speed},user)
        st.session_state['feedback'] = (ok,msg)
    st.caption('Dashboard refreshes every 0.5 s. All process durations use simulation time.')
    st.divider()
    st.caption('MODEL ASSUMPTIONS')
    st.caption('360 units/h design rate · 10 pallets · 2 s transfers · S2 bottleneck')
    st.caption('Python simulation · Streamlit interface · No broker required')


def format_value(value, unit='', precision=1):
    return '—' if value is None else f'{value:,.{precision}f}{unit}'


def press(label, cmd, args=None, key=None, disabled=False):
    if st.button(label,key=key,width='stretch',disabled=disabled):
        st.session_state['feedback'] = send(cmd,args or {},user)
        st.rerun()


def show_feedback():
    if 'feedback' in st.session_state:
        ok,msg = st.session_state['feedback']
        (st.success if ok else st.warning)(msg)


def controls(s, m):
    cols = st.columns([1,1,1,1.5])
    with cols[0]: press('▶ Start','start',key='start',disabled=s['run'] or m['estop_latched'])
    with cols[1]: press('Ⅱ Stop','stop',key='stop',disabled=not s['run'])
    with cols[2]: press('Reset alarms','reset',key='reset')
    with cols[3]:
        label = 'Release E-stop' if m['estop_active'] else '■ EMERGENCY STOP'
        press(label,'estop',{'active':not m['estop_active']},key='estop')
    if m['estop_latched']:
        st.error('E-stop latched. Release E-stop → Reset alarms → Start.')


def counters(s,k):
    cols = st.columns(5)
    for col,name,key in zip(cols,['Units loaded','Good units','Rejected units','Work in progress','Boxes packed'],['in','good','reject','wip','boxes']):
        col.metric(name,s['counts'][key])
    cols = st.columns(4)
    cols[0].metric('Throughput · rolling 600 s',format_value(k['th_ph'],' /h',0))
    cols[1].metric('Line cycle · good exits',format_value(k['line_ct_s'],' s'))
    cols[2].metric('Mean lead time',format_value(k['lead_s'],' s'))
    cols[3].metric('OEE · S2 bottleneck',format_value(k['oee']*100 if k['oee'] is not None else None,' %'))


def materials(s,m):
    cols = st.columns(4)
    for col,name in zip(cols,s['bins']):
        amount,capacity = s['bins'][name],m['material_capacity'][name]
        with col:
            st.caption(f'{name.upper()} · {amount}/{capacity}')
            st.progress(max(0,min(1,amount/capacity)))
            eta = m['refills'].get(name)
            st.caption(f'Refill arriving in {eta:.1f} sim-s' if eta is not None else 'Stock ready')


def live_cell(data):
    s,k,m = data['snapshot'],data['kpi'],data['meta']
    st.html(overview(s,m))
    counters(s,k)
    st.caption('Throughput uses the full 600-second window; it ramps up during warm-up. Values come from the running model.')
    materials(s,m)
    a,b = st.columns([1.3,1])
    with a:
        st.plotly_chart(trend(data['history'],'force_N','S2 press force (N)',color='#A78BFA',
            limits=[(105,'105 N · lower limit','#60A5FA'),(140,'140 N · quality limit','#FBBF24'),(160,'160 N · overload','#FB7185')]),width='stretch',key='live_force')
    with b:
        st.markdown('#### Active alarms')
        if s['alarms']:
            st.dataframe(pd.DataFrame(s['alarms'])[['code','sev','text']],hide_index=True,width='stretch')
        else:
            st.success('No active alarms.')
        down = k['down_s']['S2']
        st.caption(f'S2 downtime · unplanned {down["unplanned"]:.1f} s · planned {down["planned"]:.1f} s')
        st.caption('Parts conserved ✓' if k['check']['conservation'] else 'PART CONSERVATION FAILED')
        st.caption('10 unique pallets conserved ✓' if k['check']['pallet_conservation'] else 'PALLET CONSERVATION FAILED')
        st.caption('These are simulated process controls.')


def trends(data):
    h,k = data['history'],data['kpi']
    a,b = st.columns(2)
    with a: st.plotly_chart(trend(h,'throughput','Good throughput (units/h)'),width='stretch',key='throughput')
    with b: st.plotly_chart(trend(h,'oee_pct','OEE (%)','#34D399'),width='stretch',key='oee')
    st.plotly_chart(trend(h,'force_N','S2 press force (N)','#A78BFA',[(105,'Lower quality limit','#60A5FA'),(140,'Upper quality limit','#FBBF24'),(160,'Overload','#FB7185')]),width='stretch',key='force')
    c=st.columns(3)
    for col,label,key in zip(c,['Availability','Performance','Quality'],['A','P','Q']):
        col.metric(label,format_value(k[key]*100 if k[key] is not None else None,' %'))
    st.markdown(f'#### Reject codes · {data["snapshot"]["counts"]["reject"]} rejected units')
    if k['pareto']:
        st.bar_chart(pd.DataFrame({'Count':k['pareto']}))
        st.caption('One rejected unit can have more than one reject code.')
    else: st.info('No rejects recorded yet.')
    st.download_button('Download trend CSV',pd.DataFrame(h).to_csv(index=False),'syringetwin_trends.csv','text/csv')


def logs():
    for title,path in [('Alarm history','alarms'),('Operator audit','commands'),('Recent events','events')]:
        st.markdown('#### '+title)
        rows = get(path)
        if rows:
            display = pd.DataFrame(rows)
            for col in ['args','data','meas','reject_codes']:
                if col in display: display[col] = display[col].map(lambda x:json.dumps(x))
            st.dataframe(display,hide_index=True,width='stretch')
            if path=='commands':
                st.download_button('Download audit CSV',display.to_csv(index=False),'syringetwin_audit.csv','text/csv')
        else: st.caption('No records in this run yet.')


def traceability():
    serial = st.text_input('Find a serial',placeholder='SYR-B07-000001',key='serial_search').strip().upper()
    rows = get('parts?limit=20')
    if rows:
        choices = [p['serial'] for p in rows]
        selected = st.selectbox('Or choose a recent part',choices,index=0)
        lookup = serial or selected
        match = next((p for p in rows if p['serial']==lookup),None)
        if match is None:
            try: match = get('parts/'+lookup)
            except ConnectionError:
                st.warning('Serial not found in the current run.'); match=None
        if match:
            st.markdown(f'#### {lookup} · {match["status"]}')
            st.json({'measurements':match['meas'],'reject_codes':match['reject_codes'],
                     't_in':match['t_in'],'t_out':match['t_out']})
            st.dataframe(pd.DataFrame(match['events']),hide_index=True,width='stretch')
            st.download_button('Download part record',json.dumps(match,indent=2),lookup+'.json','application/json')
        table = pd.DataFrame([{k:p[k] for k in ['serial','status','t_in','t_out','reject_codes']} for p in rows])
        st.markdown('#### Recent parts')
        st.dataframe(table,hide_index=True,width='stretch')
    else: st.info('Start the line to generate serial records.')


def maintenance(data):
    s,k,m = data['snapshot'],data['kpi'],data['meta']
    st.markdown('#### S2 tool condition')
    health = k['s2']['health']
    st.progress(health,text=f'Tool health · {health*100:.1f}%')
    cols = st.columns(3)
    cols[0].metric('Last press force',format_value(s['stations']['S2']['force'],' N'))
    cols[1].metric('Predicted cycles to overload',format_value(k['s2']['cycles_to_fault'],'',0))
    cols[2].metric('Maintenance remaining',format_value(m['maintenance_remaining_s'],' sim-s'))
    st.caption('Prediction fits the latest 30 force samples. “—” means there is insufficient evidence or no rising trend.')
    a,b,c = st.columns(3)
    with a: press('Inject F201','inject_fault',{'code':'F201'},key='inject')
    with b: press('Repair S2','repair',{'station':'S2'},key='repair')
    with c: press('Schedule tool change','tool_change',{'station':'S2'},key='tool_change')
    if m['tool_change_queued']: st.info('Tool change queued until the current S2 cycle is released.')
    st.info('F201 recovery: keep the line running → Repair S2 → wait 90 sim-s → Reset alarms. The fault remains latched until repair finishes.')
    st.caption('Injected faults are identified in the audit and affected part record.')
    st.markdown('#### Material refill')
    cols = st.columns(4)
    for col,name in zip(cols,s['bins']):
        with col: press('Refill '+name,'refill',{'bin':name},key='refill_'+name)
    materials(s,m)


@st.fragment(run_every=0.5)
def dashboard():
    try:
        data = get('live')
    except ConnectionError as exc:
        st.error(str(exc))
        st.warning('Disconnected · live values are hidden until the service reconnects.')
        st.button('Retry connection',key='retry')
        return
    s,k,m = data['snapshot'],data['kpi'],data['meta']
    age = (datetime.now().astimezone()-datetime.fromisoformat(m['published_wall'])).total_seconds()
    if m['engine_error'] or age > 5:
        st.error('Engine stopped updating: '+str(m['engine_error'] or 'stale connection'))
        return
    st.markdown('<div class="eyebrow">LIVE DIGITAL TWIN / GROUP 07</div>',unsafe_allow_html=True)
    a,b = st.columns([2,1])
    with a:
        st.title('Syringe assembly cell')
        st.caption('Material input · printing · insertion · capping · inspection · packing')
    with b:
        text = 'E-STOP' if m['estop_latched'] else 'RUNNING' if s['run'] else 'STOPPED'
        colors={'GREEN':'#34D399','RED':'#FB7185','AMBER':'#FBBF24','OFF':'#94A3B8'}
        st.markdown(f'<div class="cell-status"><span style="color:{colors[s["lamp"]]}">●</span> {text} &nbsp; · &nbsp; {s["t"]/60:.1f} sim-min &nbsp; · &nbsp; {s["speed"]}×<br><small>Connected · updated {age:.1f} s ago</small></div>',unsafe_allow_html=True)
    controls(s,m)
    show_feedback()
    if page=='Live cell': live_cell(data)
    elif page=='Trends': trends(data)
    elif page=='Alarms & audit': logs()
    elif page=='Traceability': traceability()
    elif page=='Maintenance': maintenance(data)


dashboard()
