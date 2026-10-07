"""Render the CoppeliaSim cell to PNG through a virtual camera (for the report and slides).

Usage: python tools/coppelia_snapshot.py [--out docs/evidence/coppelia_cell.png] [--view iso|front|top]
Run while tools/coppelia_view.py is mirroring the twin.
"""
import argparse
import math
from pathlib import Path
from PIL import Image
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

ROOT = Path(__file__).resolve().parents[1]
VIEWS = {'iso': ([0.2, -6.4, 3.8], [5.6, 0.2, 0.9]),
         'overview': ([5.4, -9.5, 5.2], [5.4, 0.4, 1.0]),
         'front': ([5.4, -7.5, 1.8], [5.4, 0.0, 0.6]),
         'top': ([5.4, -0.45, 11.0], [5.4, -0.44, 0.5]),
         'press': ([3.6, -2.4, 1.6], [4.8, 0.0, 0.85]),
         'inspect': ([8.2, -2.5, 2.2], [9.8, 0.3, 0.95]),
         'board': ([5.4, -3.2, 2.3], [5.4, 2.7, 2.5])}


def look_at(eye, target):
    """12-value pose matrix whose +z axis points from eye to target (vision-sensor convention)."""
    z = [t - e for t, e in zip(target, eye)]
    n = math.sqrt(sum(c * c for c in z))
    z = [c / n for c in z]
    up = [0.0, 0.0, 1.0] if abs(z[2]) < 0.95 else [0.0, 1.0, 0.0]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    n = math.sqrt(sum(c * c for c in x))
    x = [c / n for c in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [x[0], y[0], z[0], eye[0], x[1], y[1], z[1], eye[1], x[2], y[2], z[2], eye[2]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT / 'docs' / 'evidence' / 'coppelia_cell.png'))
    parser.add_argument('--view', choices=VIEWS, default='iso')
    parser.add_argument('--width', type=int, default=1600)
    parser.add_argument('--height', type=int, default=900)
    args = parser.parse_args()
    sim = RemoteAPIClient().require('sim')
    # options: 1 explicit handling, 2 perspective, 4 hide body; floats: near, far, view angle, body size xyz, null colour
    cam = sim.createVisionSensor(1 | 2 | 4, [args.width, args.height, 0, 0],
                                 [0.05, 60.0, math.radians(55), 0.1, 0.1, 0.1, 0.93, 0.95, 0.92, 0, 0])
    try:
        eye, target = VIEWS[args.view]
        sim.setObjectMatrix(cam, look_at(eye, target), sim.handle_world)
        sim.handleVisionSensor(cam)
        data, (w, h) = sim.getVisionSensorImg(cam)
        img = Image.frombytes('RGB', (w, h), bytes(data)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        img.save(args.out)
        print('Saved', args.out)
    finally:
        sim.removeObjects([cam])


if __name__ == '__main__':
    main()
