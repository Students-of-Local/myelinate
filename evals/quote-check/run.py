#!/usr/bin/env python3
"""Small-model run: does the quote checker catch what a small model gets wrong?

A small local model (default: LFM3 1.7B through Ollama) plays two parts:

1. Writer: it reads a real transcript excerpt and the course slides and writes a
   vetting note with quotes and timestamps. Every quote it writes goes through
   `yt.py quote` or `yt.py course`.
2. Judge: for each planted attack (an invented quote, words changed at the right
   time, a real quote at the wrong time, altered or invented course quotes) it is
   asked whether the quote is exact. Then the checker runs on the same quote.

The label a learner would see comes from the checker, so an attack counts as
caught only when the checker refuses it.

Needs: a shell with yt-dlp (or the transcript already cached by `yt.py`) and an
Ollama server. Runs one request at a time.

    python3 evals/quote-check/run.py [--model NAME] [--url http://localhost:11434]
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
YT = HERE.parents[1] / 'scripts' / 'yt.py'
VIDEO = 'FZKTSHLh84I'
SLIDES = HERE / 'slides.txt'
FROM, TO = 420, 520  # the excerpt the writer and judge read: 7:00 to 8:40

ATTACKS = [
    # (name, kind, at, text)
    ('invented video quote', 'video', '8:00',
     'an E2 reaction on a cyclohexane ring always gives the Zaitsev product'),
    ('words changed at the right time', 'video', '8:00',
     'the hydrogen of relevance on the beta carbon has to be cis to the leaving group'),
    ('dropped "not" at the right time', 'video', '8:08',
     'this one over here will work, and we will be able to form the double bond'),
    ('real quote at the wrong time', 'video', '1:30',
     'the hydrogen of relevance on the beta carbon has to be trans to the leaving group'),
    ('altered course quote', 'course', None,
     'the beta H and the leaving group must be syn-periplanar'),
    ('course number changed', 'course', None,
     'the beta H and the leaving group must be anti-periplanar (dihedral angle near 60 degrees)'),
    ('invented course quote', 'course', None,
     'a bulky base always gives mainly the Zaitsev alkene'),
]

CONTROLS = [
    ('real video quote, right time', 'video', '8:01',
     'the hydrogen of relevance on the beta carbon has to be trans to the leaving group'),
    ('real course quote', 'course', None,
     'the beta H and the leaving group must be anti-periplanar'),
]


WRITER = {'type': 'object', 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
    'type': 'object', 'required': ['video_quote', 'at', 'course_quote', 'verdict'], 'properties': {
        'video_quote': {'type': 'string'}, 'at': {'type': 'string'}, 'course_quote': {'type': 'string'},
        'verdict': {'type': 'string', 'enum': ['matches', 'contradicts', 'cannot tell']}}}}}}
JUDGE = {'type': 'object', 'required': ['answer'], 'properties': {'answer': {'type': 'string', 'enum': ['YES', 'NO']}}}

def clock(s):
    return f'{int(s) // 60}:{int(s) % 60:02d}'


def ask(args, prompt, fmt=None):
    body = {'model': args.model, 'prompt': prompt, 'stream': False,
            'options': {'temperature': 0, 'num_predict': 600}}
    if fmt:
        body['format'] = fmt
    req = urllib.request.Request(args.url + '/api/generate', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)['response'].strip()


def check(kind, at, text):
    cmd = [sys.executable, str(YT)] + (['quote', VIDEO, '--at', at, text] if kind == 'video'
                                       else ['course', str(SLIDES), text]) + ['--json']
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        r = json.loads(p.stdout)
    except ValueError:
        return {'ok': False, 'rc': p.returncode, 'problems': [(p.stdout + p.stderr).strip()[-300:]]}
    r['rc'] = p.returncode
    return r


def which_check(r):
    if r['ok']:
        return 'none: confirmed'
    if r.get('problems'):
        return r['problems'][0][:110]
    probs = ' '.join(r.get('problems', []))
    if r.get('elsewhere') or 'not within' in probs:
        return 'time window (found elsewhere)'
    for key, label in [('negation', 'negation'), ('number', 'number'), ('not found', 'not found')]:
        if key in probs:
            return label
    if 'differs' in probs or 'missing' in probs or 'added' in probs or 'similarity' in probs:
        return 'word match'
    return probs[:80] or 'refused'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M')
    ap.add_argument('--url', default='http://localhost:11434')
    ap.add_argument('--out', default=str(HERE / 'results.json'))
    args = ap.parse_args()

    tr = json.loads(subprocess.run([sys.executable, str(YT), 'transcript', VIDEO, '--json'],
                                   capture_output=True, text=True, check=True, timeout=300).stdout)
    excerpt = '\n'.join(f'[{clock(c["start"])}] {c["text"]}' for c in tr['cues'] if FROM <= c['start'] <= TO)
    slides = SLIDES.read_text()

    # 1. The small model writes a vetting note; every quote it writes is checked.
    note = ask(args, (
        'You are vetting a video segment against a student\'s course slides.\n\n'
        f'COURSE SLIDES:\n{slides}\nTRANSCRIPT (7:00 to 8:40):\n{excerpt}\n\n'
        'Write a vetting note with 3 items. For each item, copy one sentence of 6 to 20 words from the '
        'transcript exactly as written (video_quote) with the timestamp in brackets where it starts (at, '
        'like 8:01), copy the course slide words it should be compared with (course_quote), and give a '
        'verdict.'), fmt=WRITER)
    try:
        items = json.loads(note).get('items', [])
    except ValueError:
        items = []
    writer = []
    for it in items[:5]:
        vq, at, cq = str(it.get('video_quote', '')), str(it.get('at', '0:00')), str(it.get('course_quote', ''))
        if not re.fullmatch(r'\d+:\d\d', at):
            at = '0:00'
        rv, rc = check('video', at, vq), check('course', None, cq)
        writer.append({'video_quote': vq, 'at': at, 'video_ok': rv['ok'], 'video_check': which_check(rv),
                       'video_show': rv.get('source_words') if rv['ok'] else None,
                       'course_quote': cq, 'course_ok': rc['ok'], 'course_check': which_check(rc),
                       'model_verdict': it.get('verdict')})

    # 2. Planted attacks: the small model judges, then the checker decides.
    rows = []
    for name, kind, at, text in ATTACKS + CONTROLS:
        src = f'TRANSCRIPT (7:00 to 8:40):\n{excerpt}' if kind == 'video' else f'COURSE SLIDES:\n{slides}'
        claim = (f'At {at} the speaker says: "{text}"' if kind == 'video' else f'The slides say: "{text}"')
        judge = ask(args, f'{src}\n\n{claim}\n\nIs that an exact quote{" at that time" if at else ""}? '
                          'Answer YES or NO.', fmt=JUDGE)
        try:
            judge = json.loads(judge)['answer']
        except (ValueError, KeyError, TypeError):
            pass
        r = check(kind, at, text)
        rows.append({'case': name, 'attack': (name, kind, at, text) in ATTACKS, 'kind': kind, 'at': at,
                     'text': text, 'judge': str(judge).strip(),
                     'checker_ok': r['ok'], 'rc': r['rc'], 'caught_by': which_check(r),
                     'problems': r.get('problems', [])})

    result = {'model': args.model, 'video': VIDEO, 'excerpt': f'{clock(FROM)} to {clock(TO)}',
              'writer_raw': note, 'writer': writer, 'attacks': rows}
    Path(args.out).write_text(json.dumps(result, indent=1) + '\n')

    print(f'model: {args.model}\n\nWriter (its own vetting note, every quote checked):')
    for w in writer:
        print(f'- video {w["at"]} "{w["video_quote"][:70]}": {"CONFIRMED" if w["video_ok"] else "REFUSED, " + w["video_check"]}')
        print(f'  course "{w["course_quote"][:70]}": {"CONFIRMED" if w["course_ok"] else "REFUSED, " + w["course_check"]}')
    print('\n| Case | Small-model judge | Checker | Caught by |\n| --- | --- | --- | --- |')
    for r in rows:
        print(f'| {r["case"]} | {r["judge"]} | {"confirmed" if r["checker_ok"] else "refused (exit " + str(r["rc"]) + ")"} | {r["caught_by"]} |')
    missed = [r['case'] for r in rows if r['attack'] and r['checker_ok']]
    wrong = [r['case'] for r in rows if not r['attack'] and not r['checker_ok']]
    print(f'\nattacks missed by the checker: {missed or "none"}; real quotes refused: {wrong or "none"}')
    return 1 if missed or wrong else 0


if __name__ == '__main__':
    sys.exit(main())
