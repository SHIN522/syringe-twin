"""Thin HTTP adapter, reusable when the UI is replaced by a browser app."""
import os
import requests

API_BASE = os.getenv('SYRINGETWIN_API_URL','http://127.0.0.1:8000').rstrip('/')


def get(path):
    try:
        response = requests.get(API_BASE + '/api/' + path, timeout=4)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ConnectionError('Simulation service is unavailable. Run python launch.py to start both services.') from exc


def send(cmd, args, user):
    try:
        response = requests.post(API_BASE + '/api/commands',
                                 json={'cmd':cmd,'args':args,'user':user},timeout=4)
        if response.status_code >= 400:
            detail = response.json().get('detail','Command was rejected.')
            return False, str(detail)
        return True, response.json()['message']
    except (requests.RequestException, ValueError):
        return False, 'Connection lost; command delivery could not be confirmed. Reconnect and inspect the state before retrying.'
