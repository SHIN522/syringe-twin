"""Read-only OPC UA server for the twin (DECISIONS D11).

Publishes the latest service payload every 0.5 s wall time under ns=2;s=Line1.*,
using the node IDs in docs/plc/tag_dictionary.csv. Undefined values are sent
with Bad_WaitingForInitialData quality instead of an invented number.
Bound to localhost, no security: a demonstration interface, not a plant network.
"""
import asyncio
import logging
from threading import Event, Thread
from asyncua import Server, ua

ENDPOINT = 'opc.tcp://127.0.0.1:4840/syringetwin/'
NAMESPACE = 'urn:syringetwin'
STATE_CODES = {'STOPPED': 0, 'STARVED': 1, 'RUNNING': 2, 'BLOCKED': 3, 'FAULT': 4, 'MAINT': 5}
D, I, B, S = ua.VariantType.Double, ua.VariantType.Int32, ua.VariantType.Boolean, ua.VariantType.String
DEFAULTS = {D: 0.0, I: 0, B: False, S: ''}


def flatten(payload):
    """Map one /api/live payload to {node path: (value or None, variant type)}."""
    s, k, m = payload['snapshot'], payload['kpi'], payload['meta']
    active = [a for a in s['alarms']]
    out = {
        'Line1.SimTime': (s['t'], D), 'Line1.Speed': (s['speed'], I), 'Line1.Run': (s['run'], B),
        'Line1.Lamp': (s['lamp'], S), 'Line1.Profile': (m.get('profile') or 'default', S),
        'Line1.Panel.EStopActive': (m['estop_active'], B), 'Line1.Panel.EStopLatched': (m['estop_latched'], B),
        'Line1.Alarms.Active': (','.join(a['code'] for a in active), S),
        'Line1.Alarms.AnyFault': (any(a['sev'] == 'FAULT' for a in active), B),
        'Line1.Alarms.AnyWarn': (any(a['sev'] == 'WARN' for a in active), B),
        'Line1.KPI.Throughput': (k['th_ph'], D), 'Line1.KPI.LineCycleTime': (k['line_ct_s'], D),
        'Line1.KPI.LeadTime': (k['lead_s'], D), 'Line1.KPI.OEE': (k['oee'], D),
        'Line1.KPI.A': (k['A'], D), 'Line1.KPI.P': (k['P'], D), 'Line1.KPI.Q': (k['Q'], D),
        'Line1.KPI.OEE_10min': (k['oee_win']['oee'], D),
        'Line1.KPI.S2Unplanned_s': (k['down_s']['S2']['unplanned'], D),
        'Line1.KPI.S2Planned_s': (k['down_s']['S2']['planned'], D),
        'Line1.S2.Force': (s['stations']['S2']['force'], D), 'Line1.S2.Wear': (s['stations']['S2']['wear'], D),
        'Line1.S2.Health': (k['s2']['health'], D), 'Line1.S2.CyclesToFault': (k['s2']['cycles_to_fault'], D),
        'Line1.S2.ToolOK': (m['tool_ok'], B),
    }
    for name in ('In', 'Good', 'Reject', 'WIP', 'Boxes'):
        out[f'Line1.Counts.{name}'] = (s['counts'][name.lower() if name != 'In' else 'in'], I)
    for name, st in s['stations'].items():
        base = f'Line1.Stations.{name}'
        out[f'{base}.State'] = (st['state'], S)
        out[f'{base}.StateCode'] = (STATE_CODES[st['state']], I)
        out[f'{base}.Step'] = (st['step'], S)
        out[f'{base}.Part'] = (st['part'] or '', S)
        out[f'{base}.Cycles'] = (st['cycles'], I)
    plc = m.get('plc') or {'mode': 'internal'}
    out['Line1.PLC.Mode'] = (plc['mode'], S)
    out['Line1.PLC.LinkOK'] = (plc.get('link_ok', False), B)
    coils = plc.get('coils') or {}
    for node, coil in (('Run', 'M_SYS_RUN'), ('LampGreen', 'Q_LAMP_GREEN'), ('LampAmber', 'Q_LAMP_AMBER'),
                       ('LampRed', 'Q_LAMP_RED'), ('Horn', 'Q_HORN'), ('F201', 'F201'), ('F001', 'F001'),
                       ('F002', 'F002'), ('AnyFault', 'M_ANY_FAULT'), ('F201Injected', 'F201_INJECTED'),
                       ('S2Repaired', 'M_S2_REPAIRED')):
        out[f'Line1.PLC.{node}'] = (coils.get(coil), B)
    counters = plc.get('counters') or {}
    for node, key in (('In', 'C_IN'), ('Good', 'C_GOOD'), ('Reject', 'C_REJECT'),
                      ('BoxFill', 'BOX_FILL'), ('Boxes', 'BOXES_TOTAL')):
        out[f'Line1.PLC.Counters.{node}'] = (counters.get(key), I)
    return out


class OpcUaServer:
    def __init__(self, endpoint=ENDPOINT):
        self.endpoint = endpoint
        self.latest = None
        self.ready, self.stopping = Event(), Event()
        self.error = None
        self.thread = None

    def start(self):
        self.thread = Thread(target=lambda: asyncio.run(self._main()), name='SyringeTwinOPCUA', daemon=True)
        self.thread.start()
        self.ready.wait(10)

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=5)

    def publish(self, payload):
        self.latest = flatten(payload)  # one reference swap; the server loop reads it

    async def _main(self):
        logging.getLogger('asyncua').setLevel(logging.WARNING)
        try:
            server = Server()
            await server.init()
            server.set_endpoint(self.endpoint)
            server.set_server_name('SyringeTwin digital twin')
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
            idx = await server.register_namespace(NAMESPACE)
            nodes, folders = {}, {}
            objects = server.nodes.objects
            async with server:
                self.ready.set()
                while not self.stopping.is_set():
                    values = self.latest
                    if values:
                        for path, (value, vtype) in values.items():
                            if path not in nodes:
                                parent = objects
                                parts = path.split('.')
                                for depth in range(1, len(parts)):
                                    key = '.'.join(parts[:depth])
                                    if key not in folders:
                                        folders[key] = await parent.add_object(ua.NodeId(key, idx), parts[depth - 1])
                                    parent = folders[key]
                                nodes[path] = await parent.add_variable(ua.NodeId(path, idx), parts[-1],
                                                                        DEFAULTS[vtype], varianttype=vtype)
                            if value is None:
                                dv = ua.DataValue(ua.Variant(DEFAULTS[vtype], vtype),
                                                  StatusCode=ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData))
                            else:
                                dv = ua.DataValue(ua.Variant(int(value) if vtype is I else value, vtype))
                            await nodes[path].write_value(dv)
                    await asyncio.sleep(0.5)
        except Exception as exc:  # report, never take the twin down with it
            self.error = f'{type(exc).__name__}: {exc}'
            self.ready.set()

    def status(self):
        return {'endpoint': self.endpoint, 'running': self.thread is not None and self.thread.is_alive(),
                'error': self.error}
