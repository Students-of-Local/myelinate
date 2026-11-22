#!/usr/bin/env python3
"""A stand-in for yt-dlp that serves the fixtures in this folder and behaves like YouTube where it matters.

Environment:
  FAKE_YT_LOG   file that gets one line per call (search, info ID, subs SOURCE LANGS)
  FAKE_YT_429   comma-separated caption tracks that answer HTTP 429 (or "all")
  FAKE_YT_NET   set to 1 to fail every call with a connection error

Like YouTube, a translated track (tlang= in its URL) answers 429, and so does a
second caption request in the same run; like yt-dlp, the first subtitle error
ends the whole run with exit 1.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]


def log(line):
    if os.environ.get('FAKE_YT_LOG'):
        with open(os.environ['FAKE_YT_LOG'], 'a') as f:
            f.write(line + '\n')


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def opt(name):
    return args[args.index(name) + 1] if name in args else None


if os.environ.get('FAKE_YT_NET'):
    log('net-fail')
    fail("ERROR: Unable to download API page: ('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))")

if '--flat-playlist' in args:
    log('search ' + args[-1])
    print((HERE / 'search.json').read_text())
    sys.exit(0)

if '--load-info-json' in args:
    info = json.loads(Path(opt('--load-info-json')).read_text())
    manual = '--write-subs' in args
    pool = info.get('subtitles' if manual else 'automatic_captions') or {}
    patterns = (opt('--sub-langs') or '').split(',')
    langs = [k for p in patterns for k in pool if re.fullmatch(p, k)]
    log(f"subs {'manual' if manual else 'auto'} {opt('--sub-langs')}")
    if opt('--sub-format') != 'vtt':
        fail('ERROR: fake only serves vtt')
    limited = set((os.environ.get('FAKE_YT_429') or '').split(','))
    for n, lang in enumerate(langs):
        tlang = any('tlang=' in t.get('url', '') for t in pool[lang])
        if n > 0 or tlang or lang in limited or 'all' in limited:
            fail(f"ERROR: Unable to download video subtitles for '{lang}': HTTP Error 429: Too Many Requests")
        src = HERE / f"{info['id']}.{lang}.vtt"
        if not src.is_file():
            fail(f"ERROR: Unable to download video subtitles for '{lang}': HTTP Error 404: Not Found")
        Path(f"{opt('-o')}.{lang}.vtt").write_text(src.read_text())
    sys.exit(0)

if '-J' in args:
    m = re.search(r'v=([\w-]{11})', args[-1])
    vid = m.group(1) if m else args[-1]
    log('info ' + vid)
    path = HERE / f'info_{vid}.json'
    if path.is_file():
        print(path.read_text())
        sys.exit(0)
    if vid == 'PRIVATEVID1':
        fail(f"ERROR: [youtube] {vid}: Private video. Sign in if you've been granted access to this video")
    fail(f'ERROR: [youtube] {vid}: Video unavailable')

fail('ERROR: fake yt-dlp got arguments it does not know: ' + ' '.join(args))
