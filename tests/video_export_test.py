#!/usr/bin/env python3
"""Test for scripts/video_export.py: export six seconds of the sky example and check the file.

Prints SKIP and exits 0 when this machine has no Playwright driver or no ffmpeg/ffprobe,
because the exporter never installs anything.

usage: python3 tests/video_export_test.py
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'scripts' / 'video_check.py'
EXPORTER = ROOT / 'scripts' / 'video_export.py'
SKY = ROOT / 'examples' / 'video-lesson-sky.json'

spec = importlib.util.spec_from_file_location('video_export', EXPORTER)
vx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vx)


def main():
    import shutil
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')) or not (vx.python_playwright() or vx.node_module()):
        print('SKIP: no Playwright driver or no ffmpeg/ffprobe on this machine.')
        return 0
    failures = []

    def check(ok, msg):
        print(('ok   ' if ok else 'FAIL ') + msg)
        if not ok:
            failures.append(msg)

    work = Path(tempfile.mkdtemp(prefix='video-export-test-'))
    html, mp4 = work / 'sky.html', work / 'sky.mp4'
    r = subprocess.run([sys.executable, str(CHECKER), str(SKY), '--build', str(html)], capture_output=True, text=True)
    check(r.returncode == 0 and html.is_file(), 'the checker builds the sky example')
    r = subprocess.run([sys.executable, str(EXPORTER), str(html), str(mp4), '--fps', '5', '--seconds', '6', '--width', '640', '--height', '360'],
                       capture_output=True, text=True)
    print(r.stdout[-1500:] + r.stderr[-1500:])
    if r.returncode == 3:
        print('SKIP: the exporter reports a missing tool.')
        return 0
    check(r.returncode == 0, f'the exporter exits 0 (got {r.returncode})')
    check('silent: captions only' in r.stdout, 'a lesson without clips is reported as silent')
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'json', str(mp4)],
                       capture_output=True, text=True)
    info = json.loads(p.stdout or '{}')
    vids = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
    check(bool(vids) and (vids[0].get('width'), vids[0].get('height')) == (640, 360), 'the MP4 is 640x360')
    dur = float(info.get('format', {}).get('duration') or 0)
    check(abs(dur - 6) <= 0.5, f'the MP4 lasts about 6 s ({dur:.2f} s)')
    sheet = work / 'sky-sheet.png'
    check(sheet.is_file() and sheet.stat().st_size > 1000, 'the contact sheet exists')

    if failures:
        print(f'\n{len(failures)} check(s) failed. Files are in {work}')
        return 1
    shutil.rmtree(work, ignore_errors=True)
    print('\nAll video export tests passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
