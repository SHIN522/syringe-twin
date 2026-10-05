"""Bundle the exact Python model for the browser's isolated Pyodide worker."""
import hashlib
import base64
from importlib.resources import files as resource_files
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILES = [f'twin/{name}.py' for name in
               ('__init__', 'model', 'control', 'plant', 'events', 'engine', 'commands', 'kpi')]
MODEL_FILES.append('config/line.yaml')


def main():
    files = {name: (ROOT / name).read_text(encoding='utf-8') for name in MODEL_FILES}
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in MODEL_FILES}
    (ROOT / 'web').mkdir(exist_ok=True)
    bundle = {'files': files, 'sha256': hashes, 'model': 'SyringeTwin Python engine',
              'dt': 0.1, 'seed': 7,
              'binary_files': {'zoneinfo/Asia/Kolkata': base64.b64encode(
                  resource_files('tzdata').joinpath('zoneinfo/Asia/Kolkata').read_bytes()).decode('ascii')}}
    (ROOT / 'web' / 'model_bundle.json').write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
    print(f'Bundled {len(files)} model files into web/model_bundle.json')


if __name__ == '__main__':
    main()
