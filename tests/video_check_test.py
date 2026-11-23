#!/usr/bin/env python3
"""Tests for scripts/video_check.py: the sky example is clean, the template is not, and each rule fires on a bad lesson.

Fixtures are the sky example with one thing broken, built in code. Only the broken JSON file lives on disk.

usage: python3 tests/video_check_test.py
"""
import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'scripts' / 'video_check.py'
SKY = ROOT / 'examples' / 'video-lesson-sky.json'
TEMPLATE = ROOT / 'templates' / 'video-lesson.json'
BROKEN = ROOT / 'tests' / 'fixtures' / 'video' / 'broken.json'
WORK = Path(tempfile.mkdtemp(prefix='video-check-test-'))

spec = importlib.util.spec_from_file_location('video_check', CHECKER)
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

SKY_LESSON = json.loads(SKY.read_text())
failures = []


def check(condition, message):
    if condition:
        print('PASS:', message)
    else:
        print('FAIL:', message)
        failures.append(message)


def sky():
    return copy.deepcopy(SKY_LESSON)


def problems(lesson, sources=None, final=False):
    errors, warnings, _ = vc.check(lesson, sources, final)
    return errors, warnings


def text_of(items):
    return [f'{where} {problem}' for where, problem, _ in items]


def expect(name, lesson, substring, where=None, sources=None, final=False):
    """The lesson has at least one error, and one of them contains substring (and where, if given)."""
    errors, _ = problems(lesson, sources, final)
    hit = [e for e in errors if substring in e[1] and (where is None or where in e[0])]
    detail = f'{len(errors)} error(s)' if hit else f'not found in {text_of(errors)[:4]}'
    check(len(errors) > 0 and bool(hit), f'{name}: error "{substring}" ({detail})')


def write(name, data):
    path = WORK / name
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1, ensure_ascii=False))
    return path


def run(*args):
    return subprocess.run([sys.executable, str(CHECKER), *map(str, args)], capture_output=True, text=True)


def say_beats(lesson):
    return [b for s in lesson['scenes'] for b in s['beats'] if 'say' in b]


def quotes_file(lesson):
    return write('quotes.txt', '\n\n'.join(c['quote'] for c in lesson['claims']))


def stretch(lesson, si, bi, seconds):
    """Insert plain talk sentences after beat bi of scene si until about `seconds` of narration is added."""
    filler = {'say': 'Keep that picture in mind as we go on to the next part of the story.', 'talk': True}
    n = int(seconds * lesson['wpm'] / 60 / len(filler['say'].split())) + 1
    lesson['scenes'][si]['beats'][bi + 1:bi + 1] = [dict(filler) for _ in range(n)]
    return lesson


def main():
    # Clean and template.
    errors, warnings = problems(sky(), final=True)
    check(errors == [], f'the sky example has 0 errors with --final ({text_of(errors)})')
    errors, warnings = problems(sky(), vc.load_sources([quotes_file(SKY_LESSON)]), final=True)
    check(errors == [], f'the sky example has 0 errors with --sources holding its quotes ({text_of(errors)})')
    check(not [w for w in warnings if 'quote was not found' in w[1]], 'every outside quote is found in the --sources file, so no quote warning')
    r = run(SKY, '--final', '--sources', quotes_file(SKY_LESSON))
    check(r.returncode == 0 and 'READY' in r.stdout, f'main() exits 0 and says READY for the sky example (exit {r.returncode})')

    template = json.loads(TEMPLATE.read_text())
    expect('template', template, 'blank(s) from the template')
    check('<<' in vc.check(template)[0][0][1], 'the placeholder error quotes one of the blanks')

    # Reading the file: broken JSON and ``` fences.
    r = run(BROKEN)
    check(r.returncode == 2, f'broken JSON exits 2 (got {r.returncode})')
    check(re.search(r'NOT VALID JSON: line 4, column \d+', r.stdout) is not None, f'broken JSON names its line and column ({r.stdout.splitlines()[:1]})')
    fenced = write('fenced.json', '```json\n' + SKY.read_text().strip() + '\n```\n')
    lesson, note = vc.read_lesson(fenced)
    check(lesson == SKY_LESSON and note and '```' in note, 'a ```json fence is tolerated and noted by read_lesson')
    r = run(fenced, '--final')
    check(r.returncode == 0 and r.stdout.startswith('NOTE:'), f'main() passes a fenced lesson and prints the note first (exit {r.returncode})')

    # Header rules.
    for n in (0, 4):
        d = sky()
        d['objectives'] = [f'Explain idea {i}' for i in range(n)]
        expect(f'{n} objectives', d, 'must list 1 to 3 goals', '"objectives"')
    for wpm in (129, 161, 'fast'):
        d = sky()
        d['wpm'] = wpm
        expect(f'wpm {wpm!r}', d, f'is {wpm!r}.', '"wpm"')
    for wpm in (130, 160):
        d = sky()
        d['wpm'] = wpm
        check(not [e for e in problems(d)[0] if e[0] == '"wpm"'], f'wpm {wpm} is allowed')

    # Sentence rules.
    d = sky()
    d['scenes'][2]['beats'][1]['say'] = ' '.join(['word'] * 31) + '.'
    expect('31-word sentence', d, 'says 31 words in one beat', 'Scene 3')
    d = sky()
    d['scenes'][2]['beats'][1]['say'] = ' '.join(['word'] * 30) + '.'
    check(not [e for e in problems(d)[0] if 'words in one beat' in e[1]], 'a 30-word sentence is only a warning')

    d = sky()
    del d['scenes'][2]['beats'][1]['claims']
    expect('fact sentence with no claims', d, 'has no claim ids', 'Scene 3 (Air scatters blue the most), beat 2')

    d = sky()
    beat = d['scenes'][0]['beats'][0]
    check(beat.get('talk') is True, 'fixture: the first beat is a talk beat')
    beat['say'] = 'Look up on a clear afternoon at 3 and the sky is blue.'
    expect('talk beat with a digit', d, 'is marked "talk" but has a number in it', 'Scene 1')

    d = sky()
    beat = d['scenes'][2]['beats'][1]
    beat.setdefault('show', []).append({'type': 'label', 'text': 'knock the light off in all'})
    check(vc.norm('knock the light off in all') in vc.norm(beat['say']), 'fixture: the label text is inside the narration')
    expect('screen repeats narration', d, 'repeats the narration word for word', 'Scene 3')

    d = sky()
    labels = ['alpha bravo charlie delta echo foxtrot golf hotel'.split()[:8]] * 6
    d['scenes'][2]['beats'][1].setdefault('show', []).extend({'type': 'label', 'text': ' '.join(w)} for w in labels)
    expect('over 40 screen words', d, 'words on screen.', 'Scene 3')
    check(any(re.match(r'puts \d+ words on screen', e[1]) and int(re.search(r'\d+', e[1]).group()) > 40 for e in problems(d)[0]), 'the screen-word error reports a count over 40')

    # Timing rules.
    d = sky()
    stretch(d, 2, 1, 130)
    expect('no pause for over 120 s', d, 'with no pause question', 'Scene 3')
    d = sky()
    stretch(d, 2, 1, 90)
    check(not [e for e in problems(d)[0] if 'no pause question' in e[1]], '90 s of narration right after a pause stays under the 120 s gap')

    d = sky()
    stretch(d, 2, 1, 400)
    errors = problems(d)[0]
    hit = [e for e in errors if e[0].startswith('Scene 3') and re.match(r'runs \d+\.\d minutes', e[1])]
    check(bool(hit), f'scene over 360 s: "runs N minutes" error ({len(errors)} error(s)' + ('' if hit else f', not found in {text_of(errors)[:3]}') + ')')

    # End-of-video blocks.
    d = sky()
    del d['recall']
    expect('missing recall', d, 'is missing or incomplete', '"recall"')
    d = sky()
    d['recall']['points'] = []
    expect('recall with no points', d, 'is missing or incomplete', '"recall"')
    d = sky()
    del d['practice']
    expect('missing practice', d, 'is missing or incomplete', '"practice"')
    d = sky()
    d['practice']['answer'] = ''
    expect('practice with no answer', d, 'is missing or incomplete', '"practice"')

    # Claims.
    d = sky()
    d['scenes'][2]['beats'][1]['claims'] = ['c99']
    expect('undefined claim id', d, "cites 'c99', which is not in \"claims\"", 'Scene 3')
    d = sky()
    d['practice']['claims'] = ['c42']
    expect('undefined claim id in practice', d, "cites 'c42'", '"practice"')

    # Problem lessons need a worked example, then a faded one with a pause.
    d = sky()
    d['lessonType'] = 'problem'
    expect('problem lesson with no worked example', d, 'has no worked example', 'The video')
    expect('problem lesson with no faded example', d, 'has no faded example', 'The video')
    d = sky()
    d['lessonType'] = 'problem'
    d['scenes'][4]['role'] = 'faded'
    d['scenes'][5]['role'] = 'worked'
    expect('faded before worked', d, 'puts the faded example before the worked one', 'The video')
    d = sky()
    d['lessonType'] = 'problem'
    d['scenes'][4]['role'] = 'worked'
    d['scenes'][5]['role'] = 'faded'
    check(not any('pause' in b for b in d['scenes'][5]['beats']), 'fixture: the last scene has no pause')
    expect('faded example with no pause', d, 'is a faded example with no pause', 'Scene 6')
    d = sky()
    d['lessonType'] = 'problem'
    d['scenes'][2]['role'] = 'worked'
    d['scenes'][4]['role'] = 'faded'
    check(problems(d)[0] == [], f'a problem lesson with worked then faded (with a pause) is clean ({text_of(problems(d)[0])})')

    # Terms in the first two scenes.
    d = sky()
    for s in d['scenes'][:2]:
        for b in s['beats']:
            for i, el in enumerate(b.get('show', [])):
                if el['type'] == 'term':
                    b['show'][i] = {'type': 'label', 'text': el['word']}
    expect('no term in scenes 1 and 2', d, 'name no terms', 'Scenes 1 and 2')

    # --sources: a course quote must be in the learner's files; outside quotes only warn.
    d = sky()
    d['claims'][0].update({'from': 'course', 'where': 'Lecture 2, slide 4'})
    other = write('notes.txt', 'These notes talk about clouds and rain, not about sunlight.')
    expect('course quote missing from --sources', d, "quote was not found in the learner's materials", 'Claim c1', sources=vc.load_sources([other]))
    errors, warnings = problems(sky(), vc.load_sources([other]))
    check(errors == [] and any('quote was not found in the files given' in w[1] for w in warnings), 'outside quotes missing from --sources are warnings, not errors')
    d['claims'][0]['file'] = 'missing.txt'
    expect('claim names a file not given', d, "names file 'missing.txt'", 'Claim c1', sources=vc.load_sources([other]))
    r = run(write('course.json', sky() | {'claims': [dict(SKY_LESSON['claims'][0], **{'from': 'course', 'where': 'Lecture 2, slide 4'})] + SKY_LESSON['claims'][1:]}), '--sources', other)
    check(r.returncode == 1 and "quote was not found in the learner's materials" in r.stdout, f'main() with --sources exits 1 on a missing course quote (exit {r.returncode})')

    # --final.
    d = sky()
    d['claims'][3]['status'] = 'unchecked'
    expect('--final with an unchecked claim', d, 'is not checked yet', 'Claim c4', final=True)
    check(problems(d, final=False)[0] == [], 'without --final an unchecked claim is not an error')

    # --build.
    bad = sky()
    del bad['recall']
    out = WORK / 'bad.html'
    r = run(write('bad.json', bad), '--build', out)
    check(r.returncode == 1 and not out.exists(), f'--build refuses while there are errors and writes nothing (exit {r.returncode})')
    good = sky()
    good['subtitle'] = 'And why sunsets turn red </script><script>alert(1)</script> <!-- x'
    check(problems(good, final=True)[0] == [], 'fixture: a subtitle holding </script> is still a clean lesson')
    out = WORK / 'good.html'
    r = run(write('good.json', good), '--final', '--build', out)
    check(r.returncode == 0 and out.exists(), f'--build writes the page for a clean lesson (exit {r.returncode})')
    page = out.read_text()
    blocks = re.findall(r'<script type="application/json" id="lesson">(.*?)</script>', page, re.S)
    check(len(blocks) == 1, 'the built page has exactly one lesson block')
    try:
        back = json.loads(blocks[0]) if blocks else None
    except json.JSONDecodeError as exc:
        back = f'not JSON: {exc}'
    check(back == good, 'the embedded JSON parses back to the same lesson' + ('' if back == good else f' ({str(back)[:80]})'))
    check(blocks and '</script' not in blocks[0].lower() and '<!--' not in blocks[0], 'the embedded JSON holds no raw </script or <!--')
    check(page.count('<script') == (vc.TEMPLATE.read_text().count('<script')), 'the build adds no script tags')
    check(page.replace(blocks[0], '') == re.sub(r'(<script type="application/json" id="lesson">)(.*?)(</script>)', r'\1\3', vc.TEMPLATE.read_text(), count=1, flags=re.S),
          'the build changes nothing outside the lesson block')

    # --audio-plan.
    check(vc.fnv1a('hello') == '4f9f2cab', "fnv1a('hello') == '4f9f2cab'")
    check(vc.fnv1a('') == '811c9dc5', "fnv1a('') is the FNV offset basis")
    r = run(SKY, '--audio-plan')
    plan = json.loads(r.stdout) if r.returncode == 0 else []
    beats = say_beats(SKY_LESSON)
    check(r.returncode == 0 and len(plan) == len(beats), f'--audio-plan lists one clip per narration line ({len(plan)} of {len(beats)})')
    check(all(p['text'] == b['say'] and p['clip'] == vc.fnv1a(b['say']) + '.mp3' for p, b in zip(plan, beats)), 'every clip name is fnv1a of its sentence plus .mp3')
    d = sky()
    d['audio'] = {'clips': {vc.fnv1a(beats[0]['say']): 'a.mp3', 'deadbeef': 'old.mp3'}}
    expect('stale audio clip', d, "clip(s) for sentences that changed: deadbeef", '"audio.clips"')

    # Malformed values a small model writes must give a numbered fix, never a traceback.
    d = sky(); d['scenes'][2]['beats'][1]['claims'] = [{'id': 'c5'}]
    expect('claim id written as an object', d, 'not an id')
    d = sky()
    qi = next((si, bi, k) for si, s in enumerate(d['scenes']) for bi, b in enumerate(s['beats']) for k, e in enumerate(b.get('show') or []) if e.get('type') == 'quote')
    d['scenes'][qi[0]]['beats'][qi[1]]['show'][qi[2]]['claim'] = ['c7']
    expect('quote claim written as a list', d, 'quote cites')
    d = sky(); d['claims'][0]['file'] = ['a']
    expect('claim file written as a list', d, '"file" must be one file name', sources={'a': 'x'})
    for bad in ('long', -500, 31, True):
        d = sky(); d['scenes'][2]['beats'][1]['hold'] = bad
        expect(f'hold {bad!r}', d, '"hold" is')
    for bad in ('[]', json.dumps({**SKY_LESSON, 'scenes': ['oops']})):
        r = run(write('plan-bad.json', bad), '--audio-plan')
        check(r.returncode == 0 and 'Traceback' not in r.stderr, f'--audio-plan does not crash on {bad[:20]!r}')

    if failures:
        print(f'\n{len(failures)} check(s) failed:')
        for f in failures:
            print(' -', f)
        return 1
    print('\nAll video checker tests passed.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
