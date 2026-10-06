"""Start the reusable backend on localhost:8000 (python -m twin [--profile demo] [--plc HOST[:PORT]])."""
import argparse
import os
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='python -m twin')
    parser.add_argument('--profile', help='configuration profile from config/profiles')
    parser.add_argument('--plc', metavar='HOST[:PORT]', help='PLC mode: OpenPLC Runtime over Modbus TCP')
    parser.add_argument('--opcua', action='store_true', help='serve read-only OPC UA on opc.tcp://127.0.0.1:4840')
    options = parser.parse_args()
    if options.opcua:
        os.environ['SYRINGETWIN_OPCUA'] = '1'
    if options.profile:
        os.environ['SYRINGETWIN_PROFILE'] = options.profile
    if options.plc:
        os.environ['SYRINGETWIN_PLC'] = options.plc
    uvicorn.run('twin.api:app', host='127.0.0.1', port=int(os.getenv('SYRINGETWIN_API_PORT','8000')),
                log_level='warning')
