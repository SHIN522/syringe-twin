"""SVG process overview and measured Plotly trends."""
from html import escape
import plotly.graph_objects as go

COLORS = {'RUNNING':'#34D399','STARVED':'#94A3B8','BLOCKED':'#FBBF24',
          'FAULT':'#FB7185','MAINT':'#60A5FA','STOPPED':'#64748B'}
NAMES = {'IN':'Material input','S1':'Print & cure','S2':'Press & insert',
         'S3':'Cap & mark','S4':'Inspection','OUT':'Pack & unload'}


def overview(snapshot, meta):
    nodes = list(NAMES)
    pieces = ['<svg viewBox="0 0 1240 310" xmlns="http://www.w3.org/2000/svg" role="img" font-family="Arial, sans-serif" aria-label="Live syringe assembly cell">',
              '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#3C5678"/></marker></defs>',
              '<rect width="1240" height="310" rx="16" fill="#111E32"/>',
              '<path d="M1135 218 V278 H89 V218" fill="none" stroke="#294465" stroke-width="3" stroke-dasharray="8 5" marker-end="url(#arrow)"/>',
              '<text x="610" y="299" fill="#94A3B8" font-size="12" text-anchor="middle">EMPTY PALLET RETURN · 10 s</text>']
    for i, name in enumerate(nodes):
        st, x = snapshot['stations'][name], 18+i*207
        color = COLORS[st['state']]
        reason = escape(st['reason'] or '')
        serial = escape(st['part'] or 'No part')
        pieces += [f'<g><title>{name}: {serial}. {reason}</title>',
                   f'<rect x="{x}" y="68" width="169" height="150" rx="12" fill="#14263F" stroke="{color}" stroke-width="2"/>',
                   f'<text x="{x+15}" y="96" fill="#F1F5F9" font-size="18" font-weight="700">{name}</text>',
                   f'<circle cx="{x+149}" cy="91" r="5" fill="{color}"/>',
                   f'<text x="{x+15}" y="119" fill="#B7C7DB" font-size="12">{escape(NAMES[name])}</text>',
                   f'<text x="{x+15}" y="147" fill="{color}" font-size="12" font-weight="700">{st["state"]}</text>',
                   f'<text x="{x+15}" y="172" fill="#E2E8F0" font-size="12">{escape(st["step"])}</text>',
                   f'<text x="{x+15}" y="200" fill="#94A3B8" font-size="10">{serial}</text></g>']
        if i < 5:
            pieces.append(f'<path d="M{x+170} 144 H{x+201}" stroke="#3C5678" stroke-width="3" marker-end="url(#arrow)"/>')
        if i < 4:
            buf = f'B{i+1}'
            occupied = len(snapshot['buffers'][buf])
            reserved = sum(tr['destination']==buf for tr in meta['transfers'])
            pieces += [f'<text x="{x+188}" y="38" fill="#A9BBD0" font-size="11" text-anchor="middle">{buf}</text>',
                       f'<text x="{x+188}" y="56" fill="#38BDF8" font-size="11" text-anchor="middle">{occupied}+{reserved}/{meta["buffer_capacity"][buf]}</text>']
    pieces += ['<path d="M931 218 V246" stroke="#FB7185" stroke-width="2"/>',
               f'<text x="931" y="262" fill="#FB7185" font-size="12" text-anchor="middle">REJECT BIN · {snapshot["counts"]["reject"]}</text>',
               f'<text x="24" y="28" fill="#7D93AF" font-size="12">10 PALLETS · {len(meta["transfers"])} IN TRANSIT · {meta["empty_pallets"]} AVAILABLE AT IN</text>']
    for tr in meta['transfers']:
        if tr['source'] not in nodes or tr['destination']=='RETURN':
            continue
        i = nodes.index(tr['source'])
        p = 1-tr['remaining']/tr['total']
        x = 18+i*207+174+p*25
        pieces.append(f'<circle cx="{x:.1f}" cy="144" r="5" fill="#38BDF8"><title>Pallet {tr["pallet"]} in transit</title></circle>')
    return ''.join(pieces)+'</svg>'


def trend(history, field, title, color='#38BDF8', limits=None):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[x['t']/60 for x in history],y=[x[field] for x in history],
                            mode='lines',line={'color':color,'width':2},name=title,connectgaps=False))
    for value,label,c in limits or []:
        fig.add_hline(y=value,line_dash='dash',line_color=c,
                      annotation_text=label,annotation_position='top left')
    fig.update_layout(height=265,margin=dict(l=20,r=15,t=35,b=30),title={'text':title,'font':{'size':14}},
                      template='plotly_dark',paper_bgcolor='#111E32',plot_bgcolor='#111E32',
                      font_color='#B7C7DB',xaxis_title='Simulation time (min)',showlegend=False,
                      uirevision=title)
    fig.update_xaxes(gridcolor='#203550')
    fig.update_yaxes(gridcolor='#203550')
    return fig
