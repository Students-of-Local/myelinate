#!/usr/bin/env python3
"""A stand-in for yt-dlp that serves the fixtures in this folder and fails the way YouTube does.

Environment:
  FAKE_YT_LOG          file that gets each call's argv as one JSON line
  FAKE_YT_429          comma-separated tracks that answer HTTP 429: "en-orig" (any video),
                       "HHHHHHHHHHH:es-orig" (one video), or "all"
  FAKE_YT_ALLOW_TLANG  set to 1 to serve a translated track instead of answering 429

Like YouTube, a translated track (tlang= in its URL) answers 429, and so does a
request for more than one language in one --sub-langs. Like yt-dlp, --sub-langs
items are regexes matched to the whole key, --write-subs and --write-auto-subs
together pool manual and auto tracks, and the first subtitle error ends the run
with exit 1.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]

if os.environ.get('FAKE_YT_LOG'):
    with open(os.environ['FAKE_YT_LOG'], 'a') as f:
        f.write(json.dumps(args) + '\n')


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def opt(name):
    return args[args.index(name) + 1] if name in args else None


if '--flat-playlist' in args:
    print((HERE / 'search.json').read_text())
    sys.exit(0)

if '--load-info-json' in args:
    info = json.loads(Path(opt('--load-info-json')).read_text())
    pool = {}
    if '--write-subs' in args:
        pool.update(info.get('subtitles') or {})
    if '--write-auto-subs' in args:
        pool.update({k: v for k, v in (info.get('automatic_captions') or {}).items() if k not in pool})
    patterns = (opt('--sub-langs') or '').split(',')
    langs = [k for p in patterns for k in pool if re.fullmatch(p, k)]
    if opt('--sub-format') != 'vtt':
        fail('ERROR: fake only serves vtt')
    limited = set((os.environ.get('FAKE_YT_429') or '').split(','))
    for n, lang in enumerate(langs):
        tlang = any('tlang=' in t.get('url', '') for t in pool[lang]) and not os.environ.get('FAKE_YT_ALLOW_TLANG')
        if n > 0 or tlang or {lang, f"{info['id']}:{lang}", 'all'} & limited:
            fail(f"ERROR: Unable to download video subtitles for '{lang}': HTTP Error 429: Too Many Requests")
        src = HERE / f"{info['id']}.{lang}.vtt"
        if not src.is_file():
            fail(f"ERROR: Unable to download video subtitles for '{lang}': HTTP Error 404: Not Found")
        Path(f"{opt('-o')}.{lang}.vtt").write_text(src.read_text())
    if len(patterns) > 1:
        fail(f"ERROR: Unable to download video subtitles for '{patterns[1]}': HTTP Error 429: Too Many Requests")
    sys.exit(0)

if '-J' in args:
    m = re.search(r'v=([\w-]{11})', args[-1])
    vid = m.group(1) if m else args[-1]
    path = HERE / f'info_{vid}.json'
    if path.is_file():
        print(path.read_text())
        sys.exit(0)
    fail(f'ERROR: [youtube] {vid}: Video unavailable')

fail('ERROR: fake yt-dlp got arguments it does not know: ' + ' '.join(args))
