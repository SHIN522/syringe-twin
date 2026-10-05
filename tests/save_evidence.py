"""Generate measured evidence for this rebuilt MVP; no inherited results."""
from pathlib import Path
import json
from time import perf_counter
from test_simulation import perfect_config
from twin.engine import Engine
from twin.kpi import calculate
from dashboard_visuals import overview

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs'/'evidence'
OUT.mkdir(parents=True,exist_ok=True)
e=Engine(perfect_config())
e.command('start',user='Evidence')
start=perf_counter()
e.advance(300)
before=e.state.counts['good']
integral=e.state.wip_integral
e.advance(3600)
runtime=perf_counter()-start
completed=[x for x in e.state.completions if 300<x[0]<=3900]
wip=(e.state.wip_integral-integral)/3600
lead=sum(x[1] for x in completed)/len(completed)
err=abs(wip-len(completed)/3600*lead)/wip
summary={'model':'Reconstructed Streamlit MVP','scenario':'Wear disabled; quality noise disabled; bins auto-refill',
         'warmup_s':300,'measurement_s':3600,'total_sim_s':3900,
         'good_in_measured_hour':e.state.counts['good']-before,
         'completed_in_window':len(completed),'wip_avg_window':wip,
         'lead_s_all_window':lead,'little_error':err,'headless_wall_s':runtime,
         'checks':calculate(e.state)['check']}
(OUT/'baseline_measurements.json').write_text(json.dumps(summary,indent=2))
demo=Engine()
demo.command('start',user='Evidence')
demo.advance(200)
payload=demo.payload()
(OUT/'demo_snapshot.json').write_text(json.dumps(payload,indent=2))
(OUT/'cell_overview.svg').write_text(overview(payload['snapshot'],payload['meta']))
print(json.dumps(summary,indent=2))
