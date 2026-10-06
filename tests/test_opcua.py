"""OPC UA: a real client reads twin values by the node IDs in the tag dictionary."""
import asyncio
import socket
import time
from asyncua import Client, ua
from twin.model import load_config
from twin.opcua_server import OpcUaServer
from twin.service import Service


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_client_reads_live_twin_values(tmp_path):
    endpoint = f'opc.tcp://127.0.0.1:{free_port()}/syringetwin/'
    service = Service(tmp_path, config=load_config('demo'), opcua=OpcUaServer(endpoint))
    try:
        service.opcua.start()
        assert service.opcua.error is None
        service.command('start', {}, 'QA')
        with service.lock:
            service.engine.advance(300)
            service.sample()
        time.sleep(1.2)  # server loop publishes every 0.5 s

        async def read():
            async with Client(endpoint) as client:
                idx = await client.get_namespace_index('urn:syringetwin')
                node = lambda path: client.get_node(ua.NodeId(path, idx))
                good = await node('Line1.Counts.Good').read_value()
                force = await node('Line1.S2.Force').read_value()
                state = await node('Line1.Stations.S2.State').read_value()
                profile = await node('Line1.Profile').read_value()
                mode = await node('Line1.PLC.Mode').read_value()
                plc_run = await node('Line1.PLC.Run').read_data_value(raise_on_bad_status=False)
                return idx, good, force, state, profile, mode, plc_run
        idx, good, force, state, profile, mode, plc_run = asyncio.run(read())
        s = service.engine.state
        assert idx == 2
        assert good == s.counts['good'] > 0
        assert abs(force - s.stations['S2'].force) < 1e-9
        assert state == s.stations['S2'].state
        assert profile.startswith('Demo profile') and mode == 'internal'
        assert plc_run.StatusCode.value == ua.StatusCodes.BadWaitingForInitialData  # no PLC: no fake value
    finally:
        service.close()
