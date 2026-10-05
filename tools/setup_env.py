"""Install into this project's virtual environment, without altering global Python."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dev', action='store_true')
    options = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or newer is required.')
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    requirement = 'requirements-dev.txt' if options.dev else 'requirements.txt'
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / requirement)], check=True)
    subprocess.run([str(python), str(ROOT / 'tools/build_web.py')], check=True)
    print('Ready. Run Start_Windows.bat, or .venv Python with launch.py.')


if __name__ == '__main__':
    main()
