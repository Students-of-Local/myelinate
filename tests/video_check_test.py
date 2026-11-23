#!/usr/bin/env python3
"""Tests for scripts/video_check.py: the sky example is clean, the template is not, and each rule fires on a bad lesson.

Fixtures are built in code: the sky example (checked against its NASA source text) and a small course lesson on
osmosis (checked against evals/make-video/sources/osmosis and a timed lecture transcript), each with one thing broken.
Only the broken JSON file and the synthetic transcript live on disk, in tests/fixtures/video/.

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
SKY_SRC = ROOT / 'examples' / 'video-lesson-sky-source.md'
TEMPLATE = ROOT / 'templates' / 'video-lesson.json'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'video'
BROKEN = FIXTURES / 'broken.json'
TRANSCRIPT = FIXTURES / 'lecture-transcript.txt'
OSMOSIS_DIR = ROOT / 'evals' / 'make-video' / 'sources' / 'osmosis'
SLIDE5 = 'In a hypertonic solution, the cell gains water and swells.'
WORK = Path(tempfile.mkdtemp(prefix='video-check-test-'))
REVIEW = {'by': 'test', 'date': '2026-11-22', 'result': 'pass'}

spec = importlib.util.spec_from_file_location('video_check', CHECKER)
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

SKY_LESSON = json.loads(SKY.read_text())
SKY_SOURCES = vc.load_sources([SKY_SRC])
OSMOSIS_SOURCES = vc.load_sources([OSMOSIS_DIR, TRANSCRIPT])
failures = []


def check(condition, message):
    if condition:
        print('PASS:', message)
    else:
        print('FAIL:', message)
        failures.append(message)


def sky():
    """The sky example without its recorded review, so each test adds only what it checks."""
    lesson = copy.deepcopy(SKY_LESSON)
    lesson.pop('review', None)
    return lesson


def reviewed(lesson):
    lesson['review'] = dict(REVIEW)
    return lesson


def claim(cid, text, file, where, quote, **extra):
    return {'id': cid, 'text': text, 'from': 'course', 'where': where, 'source': file, 'file': file, 'quote': quote, **extra}


def osmosis():
    """A small course lesson: slides, notes and a timed lecture transcript, with slide 5's planted error flagged."""
    return {
        'format': 'myelinate-video/1', 'title': 'Osmosis and the three beakers', 'lessonType': 'concept', 'wpm': 145,
        'learner': {'kind': 'course', 'course': 'BIO 101', 'materials': ['slides', 'notes', 'lecture video']},
        'objectives': ['Explain which way water moves in each solution'],
        'question': 'Which way does water move in each beaker?',
        'calc': [{'id': 'k1', 'expr': '500 * 0.9 / 100', 'value': 4.5},
                 {'id': 'k2', 'expr': 'k1 * 4', 'value': 18}],
        'claims': [
            claim('c1', 'Osmosis is the diffusion of water across a selectively permeable membrane.', 'bio101-slides.md', 'Slide 1',
                  'Osmosis is the diffusion of water across a selectively permeable membrane.'),
            claim('c2', 'In a hypertonic solution water leaves the cell and it shrinks.', 'my-notes.md', 'Notes, Sept 18, line 1',
                  'Hypertonic = more solute OUTSIDE the cell. Water leaves the cell and it shrinks.'),
            claim('c3', 'Slide 5 says a cell in a hypertonic solution gains water and swells.', 'bio101-slides.md', 'Slide 5', SLIDE5,
                  status='conflict', other='c2',
                  note='Slide 5 says the cell swells; the notes and the lecture say it loses water. Ask the professor which the exam uses.'),
            claim('c5', 'Normal saline is 0.9 percent salt and isotonic to red blood cells.', 'lecture-transcript.txt', 'Lecture video, 1:43',
                  'Normal saline is 0.9 percent salt, and it is isotonic to red blood cells.'),
        ],
        'scenes': [
            {'id': 's1', 'title': 'The question', 'role': 'intro', 'beats': [
                {'say': 'Your exam shows three red blood cells in three beakers.', 'talk': True,
                 'show': [{'type': 'title', 'text': 'Osmosis and tonicity'}]},
                {'say': 'Osmosis is the diffusion of water across a selectively permeable membrane.', 'claims': ['c1'],
                 'show': [{'type': 'term', 'word': 'Osmosis', 'meaning': 'Water diffusing across a membrane'}]}]},
            {'id': 's2', 'title': 'Hypertonic', 'role': 'explain', 'beats': [
                {'say': 'In a hypertonic solution, water leaves the cell and it shrinks.', 'claims': ['c2'],
                 'show': [{'type': 'term', 'word': 'Hypertonic', 'meaning': 'More solute outside'}]},
                {'say': 'Careful: your slide five says the cell gains water and swells, but your notes say water leaves and it shrinks.',
                 'claims': ['c2', 'c3']},
                {'pause': {'ask': 'Water leaves a cell in a hypertonic beaker. What happens to its size?', 'choices': ['It shrinks', 'It swells'],
                           'answer': 'It shrinks', 'why': 'Water leaves the cell and it shrinks.', 'claims': ['c2']}}]},
            {'id': 's3', 'title': 'Normal saline', 'role': 'example', 'beats': [
                {'say': 'Normal saline is zero point nine percent salt, and it is isotonic to red blood cells.', 'claims': ['c5'],
                 'show': [{'type': 'table', 'columns': ['Bag', 'Salt'], 'rows': []},
                          {'type': 'row', 'cells': ['Saline', '0.9%'], 'claims': ['c5']}]},
                {'say': 'A five hundred milliliter bag of it holds four point five grams of salt.', 'claims': ['k1'],
                 'show': [{'type': 'equation', 'text': '500 × 0.9 / 100 = 4.5 g', 'claims': ['k1']}]},
                {'say': 'Four of those bags hold eighteen grams.', 'claims': ['k2']},
                {'pause': {'ask': 'How many grams of salt are in four bags of normal saline?', 'answer': '18 grams',
                           'why': 'Each bag of five hundred milliliters holds four point five grams, and four bags hold four times that.', 'claims': ['k1', 'k2']}}]},
        ],
        'recall': {'ask': 'Look away and name what happens in each beaker.',
                   'points': ['Hypertonic: water leaves, the cell shrinks.', 'Hypotonic: water enters.']},
        'practice': {'ask': 'A cell sits in a beaker with more solute outside. Which way does water move?',
                     'answer': 'Out of the cell, so it shrinks.', 'claims': ['c2']},
    }


def beat(lesson, scene, index):
    return lesson['scenes'][scene]['beats'][index]


def problems(lesson, sources=None, final=False):
    errors, warnings, _ = vc.check(lesson, sources, final)
    return errors, warnings


def badge(lesson, sources=None):
    return vc.check(lesson, sources)[2]['verification']


def text_of(items):
    return [f'{where} {problem}' for where, problem, _ in items]


def expect(name, lesson, substring, where=None, sources=None, final=False):
    """The lesson has at least one error, and one of them contains substring (and where, if given)."""
    errors, _ = problems(lesson, sources, final)
    hit = [e for e in errors if substring in e[1] and (where is None or where in e[0])]
    detail = f'{len(errors)} error(s)' if hit else f'not found in {text_of(errors)[:4]}'
    check(len(errors) > 0 and bool(hit), f'{name}: error "{substring}" ({detail})')
    return hit


def clean(name, lesson, sources=None, final=False):
    errors = problems(lesson, sources, final)[0]
    check(errors == [], f'{name}: no errors ({text_of(errors)[:4]})')


def absent(name, lesson, substring, sources=None, final=False):
    """No error contains substring."""
    errors = problems(lesson, sources, final)[0]
    hit = [e for e in errors if substring in e[1]]
    check(not hit, f'{name}: no error "{substring}" ({text_of(hit)[:2]})')


def write(name, data):
    path = WORK / name
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1, ensure_ascii=False))
    return path


def run(*args):
    return subprocess.run([sys.executable, str(CHECKER), *map(str, args)], capture_output=True, text=True)


def say_beats(lesson):
    return [b for s in lesson['scenes'] for b in s['beats'] if 'say' in b]


def stretch(lesson, si, bi, seconds):
    """Insert plain talk sentences after beat bi of scene si until about `seconds` of narration is added."""
    filler = {'say': 'Keep that picture in mind as we go on to the next part of the story.', 'talk': True}
    n = int(seconds * lesson['wpm'] / 60 / len(filler['say'].split())) + 1
    lesson['scenes'][si]['beats'][bi + 1:bi + 1] = [dict(filler) for _ in range(n)]
    return lesson


def main():
    old_rules()
    quote_match()
    timestamps()
    calcs()
    numbers()
    exact_marks()
    coverage()
    symbols()
    conflicts()
    short_quotes()
    reveal_after_pause()
    badges()
    pause_and_length()
    show_types()
    if failures:
        print(f'\n{len(failures)} check(s) failed:')
        for f in failures:
            print(' -', f)
        return 1
    print('\nAll video checker tests passed.')
    return 0


def old_rules():
    # Clean and template.
    clean('the sky example without --sources', sky())
    clean('the sky example with --sources holding its NASA text', sky(), SKY_SOURCES)
    clean('the sky example with a recorded review and --final', reviewed(sky()), SKY_SOURCES, final=True)
    expect('--final with no review', sky(), 'is missing.', '"review"', SKY_SOURCES, final=True)
    expect('--final with no --sources', reviewed(sky()), 'needs --sources.', '--final', final=True)
    d = reviewed(sky())
    d['review']['result'] = 'fail'
    expect('a failed review', d, 'failed.', '"review"', SKY_SOURCES)
    d['review'] = {'by': 'test', 'result': 'pass'}
    expect('a review with no date', d, 'must be {"by"', '"review"', SKY_SOURCES)
    r = run(SKY, '--sources', SKY_SRC)
    check(r.returncode == 0 and 'READY' in r.stdout, f'main() exits 0 and says READY for the sky example with its sources (exit {r.returncode})')
    r = run(write('sky-reviewed.json', reviewed(sky())), '--final', '--sources', SKY_SRC)
    check(r.returncode == 0 and 'READY' in r.stdout, f'main() --final exits 0 for the reviewed sky example (exit {r.returncode})')

    template = json.loads(TEMPLATE.read_text())
    expect('template', template, 'blank(s) from the template')
    check('<<' in vc.check(template)[0][0][1], 'the placeholder error quotes one of the blanks')

    # Reading the file: broken JSON, repairs and ``` fences.
    r = run(write('unfixable.json', '{\n "format": "myelinate-video/1",\n "title": "x",\n "wpm": ,\n "scenes": []\n}\n'))
    check(r.returncode == 2, f'JSON with a missing value exits 2 (got {r.returncode})')
    check(re.search(r'NOT VALID JSON: line 4, column \d+', r.stdout) is not None, f'broken JSON names its line and column ({r.stdout.splitlines()[:1]})')
    bcopy = write('broken-copy.json', BROKEN.read_text())
    r = run(bcopy)
    check(r.returncode == 1 and r.stdout.startswith('NOTE: The file was not valid JSON. Repaired') and 'line 4: added a missing comma' in r.stdout,
          f'a missing comma is repaired, named and the check goes on (exit {r.returncode}, {r.stdout.splitlines()[:1]})')
    check(json.loads(bcopy.read_text())['wpm'] == 145, 'the repaired file is saved as valid JSON')
    check(BROKEN.read_text().count(',') == 1, 'the broken fixture itself is untouched')
    # Regression (EBE run 4): a 1.7B echoed the skill inside a made-up tool call and wrote no lesson. The repair
    # kept the skill's inline "part" example as the lesson, and the eval counted it as its best draft.
    echo = ('<tool_call>\n<parameter=content>\n4. **Six minutes or less per file.** For more, make several files, each with '
            '`"part": {"n": 1, "of": 3, "series": "<the whole topic>"}`. Each part is its own video.\n\nSo p = 260/400 = 0.65.\n')
    path = write('echo.json', echo)
    r = run(path)
    check(r.returncode == 2 and r.stdout.startswith('NOT A LESSON') and path.read_text() == echo,
          f'copied instructions holding one small JSON object are not a lesson, and the file is left alone (exit {r.returncode}, {r.stdout.splitlines()[:1]})')

    def fixed(text):
        got = vc.repair_json(text)
        return (got[0], ' | '.join(got[1])) if got else (None, '')
    # The slips a 1.7B model made in the small-model run (2026-11-22), each in its real shape.
    o, f = fixed('{"beats": [\n {"pause": {"ask": "Which?", "answer": "A", "claims": ["c3"]},\n {"say": "Next.", "claims": ["c3"]}\n]}')
    check(o == {'beats': [{'pause': {'ask': 'Which?', 'answer': 'A', 'claims': ['c3']}}, {'say': 'Next.', 'claims': ['c3']}]} and 'closed a { left open' in f,
          f'a pause beat missing its outer }} is closed where it belongs ({o}, {f})')
    o, f = fixed('{"claims": [\n {"id": "c1"},\n ],\n "scenes": []}')
    check(o == {'claims': [{'id': 'c1'}], 'scenes': []} and 'removed a comma before ]' in f, f'a comma before ] is removed ({o}, {f})')
    o, f = fixed('{"claims": [\n {"id": "c1"}\n ]\n },\n "calc": [],\n "scenes": []\n}')
    check(o == {'claims': [{'id': 'c1'}], 'calc': [], 'scenes': []} and 'line 4: removed an extra }' in f, f'an extra }} that closed the lesson early is removed ({o}, {f})')
    o, f = fixed('{"show": [{"type": "arrow", "from": "p^2", "to": "AA"}, "label": "AA odds"}]}')
    check(o == {'show': [{'type': 'arrow', 'from': 'p^2', 'to': 'AA', 'label': 'AA odds'}]}, f'an object closed one key early is reopened ({o}, {f})')
    o, f = fixed('{"say": "Not because we get closer to the Sun.""}\n')
    check(o == {'say': 'Not because we get closer to the Sun.'} and 'doubled' in f, f'a doubled closing quote is removed ({o}, {f})')
    o, f = fixed('<tool_call>\n<function=write>\n<parameter=content>\n{"title": "T"}\n</parameter>\n</function>\n</tool_call>')
    check(o == {'title': 'T'} and 'before the first {' in f, f'a made-up tool call around the JSON is dropped ({o}, {f})')
    o, f = fixed('{"title": "T"}\n\nNow run the checker? We have no shell: "x": 1')
    check(o == {'title': 'T'} and 'after the last }' in f, f'words after the object are dropped ({o}, {f})')
    o, f = fixed('{"say": "A set {1, 2} and ] marks", "n": 1}}\n')
    check(o is None or o == {'say': 'A set {1, 2} and ] marks', 'n': 1}, f'a brace inside text is never touched ({o})')
    o, f = fixed('{"say": "one",\n "text": "a line\nbreak"}')
    check(o == {'say': 'one', 'text': 'a line break'} and 'line break inside text' in f, f'a raw line break inside text becomes a space ({o}, {f})')
    # Three more from the 2026-11-23 rerun.
    o, f = fixed('{"steps": ["a", "b"],,\n "claims": ["c5"]}')
    check(o == {'steps': ['a', 'b'], 'claims': ['c5']} and 'doubled ,' in f, f'a doubled comma becomes one ({o}, {f})')
    o, f = fixed('{"claims": [\n {"id": "c14", "text": "t",},]\n],\n "calc": []}')
    check(o == {'claims': [{'id': 'c14', 'text': 't'}], 'calc': []} and 'removed an extra ]' in f, f'a ] one too many right after a close is removed ({o}, {f})')
    o, f = fixed('{"title": "T"}\n```\n\nWe need to fix all issues per the checker output.')
    check(o == {'title': 'T'} and 'after the last }' in f, f'a closing ``` fence and notes after the object are dropped ({o}, {f})')
    o, f = fixed('{"claims": [{"id": "c1", "text": "Tilted toward the Sun.",", "changes": true}, {"id": "c2"}],,}')
    check(o == {'claims': [{'id': 'c1', 'text': 'Tilted toward the Sun.', 'changes': True}, {'id': 'c2'}]} and 'stray ",' in f,
          f'a stray ", after a sentence is removed ({o}, {f})')
    o, f = fixed('{"a": 1, ",": 2, "b": [1,]}')
    check(o == {'a': 1, ',': 2, 'b': [1]}, f'a key named "," is kept while another slip is repaired ({o}, {f})')
    long_line = '{"claims": [{"id": "c1", "text": "' + 'word ' * 300 + '", "from": "course"}, "type": "title": {"text": "T"}]}'
    r = run(write('long-line.json', long_line))
    spot = next((ln for ln in r.stdout.splitlines() if 'The slip is at' in ln), '')
    check(r.returncode == 2 and re.search(r'"type">>> : "title"', spot) is not None,
          f'a slip far along a long line is quoted where it is ({r.stdout.splitlines()[1:2]})')
    # Three more from runs5 (2026-11-23), each of which threw away a whole draft.
    o, f = fixed('{\n "title": "T",\n "practice": {"claims": ["c3"]}\n}\n\n</parameter>\n}')
    check(o == {'title': 'T', 'practice': {'claims': ['c3']}} and 'after the last }' in f,
          f'a stray }} after a tool call wrapper, with nothing else after the object, is dropped ({o}, {f})')
    o, f = fixed('{"scenes": [{"beats": [{"say": "a"}}, {"say": "b"}]}]}')
    check(o == {'scenes': [{'beats': [{'say': 'a'}, {'say': 'b'}]}]} and 'removed an extra }' in f,
          f'an extra }} mid-file is still removed, and both beats stay in one scene ({o}, {f})')
    o, f = fixed('{"scenes": [{"beats": [{"say": "a"}}, {"say": "b"}]}]}\n</parameter>\n}')
    check(o == {'scenes': [{'beats': [{'say': 'a'}, {'say': 'b'}]}]}, f'... also when a wrapper tag and a stray }} follow ({o}, {f})')
    o, f = fixed('{"materials": ["nasa.gov/seasons/", \'nasa.gov/seasons/\'], "n": 1}')
    check(o == {'materials': ['nasa.gov/seasons/', 'nasa.gov/seasons/'], 'n': 1} and 'single quotes' in f, f"a 'single-quoted' value becomes a string ({o}, {f})")
    o, f = fixed('{"calc": [{"id": "k4", "expr": "k3 / 3", "value": 3.333...},\n {"id": "k5", "value": 0.5\u2026}]}')
    check(o == {'calc': [{'id': 'k4', 'expr': 'k3 / 3', 'value': 3.333}, {'id': 'k5', 'value': 0.5}]} and 'after the number 3.333' in f,
          f'... after a decimal value is dropped and the digits kept ({o}, {f})')
    for bad in ('{"values": [0.1, 0.2, 0.3...]}', '{"items": [1, 2, 3\u2026]}', '{"value": 2...}'):
        check(fixed(bad)[0] is None, f'... that may stand in for left-out items is refused: {bad}')
    for bad in ("{\"say\": 'Earth's tilt', \"n\": 1}", "{\"say\": 'two\nlines'}", '{"title": "T"}\n</parameter>\n}, "n": 1}'):
        check(fixed(bad)[0] is None, f'no guess for {bad[:30]!r}')
    r = run(write('elided.json', '{\n "title": "T",\n "claims": [\n  ...\n ],\n "scenes": [{...}]\n}\n'))
    check(r.returncode == 2 and 'leaves parts out with ...' in r.stdout, f'a draft that skips parts with ... is told to write them out ({r.stdout.splitlines()[:3]})')
    r = run(write('not-elided.json', '{\n "title": "T",\n "wpm": ,\n "say": "and so..."\n}\n'))
    check(r.returncode == 2 and 'leaves parts out' not in r.stdout, 'a ... inside narration is not read as a skipped part')
    for bad in ('{"expr": "2*k1"? Wait, recompute.", "value": 1}', '{"lang": "en"}\n<parameter=part>\n{"n": 1}', 'no object here', '{"a": tru}',
                '{"learner": {...}, "n": 1}', '{"title": "A"}\n</parameter>\n}</think>{\n "title": "B"}'):
        check(fixed(bad)[0] is None, f'no guess for {bad[:30]!r}')
    fenced = write('fenced.json', '```json\n' + SKY.read_text().strip() + '\n```\n')
    lesson, note = vc.read_lesson(fenced)
    check(lesson == SKY_LESSON and note and '```' in note, 'a ```json fence is tolerated and noted by read_lesson')
    r = run(fenced, '--sources', SKY_SRC)
    check(r.returncode == 0 and r.stdout.startswith('NOTE:'), f'main() passes a fenced lesson and prints the note first (exit {r.returncode})')

    # Slips with one right answer are fixed before the check, and named.
    t = sky()
    t['claims'][0]['file'] = t['claims'][0]['file'].replace('.md', 'x.md')
    t['claims'][1]['from'] = t['claims'][1]['file']
    first = t['scenes'][0]['beats']
    first.insert(1, {'show': [{'type': 'term', 'word': 'Scatter', 'meaning': 'bounce off in new directions'}]})
    first[0]['say'] = first[0]['say'].rstrip('.') + ' = done.'
    srcs = vc.load_sources([SKY_SRC])
    untidy = copy.deepcopy(t)
    done = vc.tidy(t, srcs)
    first = t['scenes'][0]['beats']
    check(t['claims'][0]['file'] == sky()['claims'][0]['file'] and any('close to' in x for x in done), f'a file name one slip off a given file is corrected ({done})')
    check(t['claims'][1]['from'] == 'outside', 'a file name in "from" becomes "outside" when "where" is a web address')
    check(len(first) == len(sky()['scenes'][0]['beats']) and first[0]['show'][-1]['word'] == 'Scatter', 'a beat that only shows joins the sentence before it')
    check(' equals done.' in first[0]['say'], 'a spaced = in narration reads "equals"')
    check(vc.tidy(sky(), srcs) == [], 'a clean lesson is left alone')
    said = sky()
    said['scenes'][0]['beats'][0]['say'] = 'Look up on a clear afternoon (c1, c2) and the sky is blue.'
    done_ids = vc.tidy(said, srcs)
    check(said['scenes'][0]['beats'][0]['say'] == 'Look up on a clear afternoon and the sky is blue.' and any('(k1)' in x for x in done_ids),
          f'claim ids said in the narration are removed ({said["scenes"][0]["beats"][0]["say"]!r})')

    # A small model copies the worked example's sentences into other topics (runs4, 2026-11-23).
    osmo_src = vc.load_sources([ROOT / 'evals' / 'make-video' / 'sources' / 'osmosis'])
    if osmo_src:
        ex = sky()
        ex['claims'] = [dict(ex['claims'][0], file=sorted(osmo_src)[0])]
        b0 = ex["scenes"][0]["beats"][0]
        b0["say"], b0["talk"] = 'Each color travels as a wave, and blue waves are shorter than red ones.', True
        errs = [e[1] for e in vc.check(ex, osmo_src)[0] if e[0].startswith('Scene 1 ') and e[0].endswith('beat 1')]
        check(any('copies the worked example' in e for e in errs), f'a sky sentence in an osmosis lesson is flagged ({[e for e in errs if "copies" in e][:1]})')
        fixes = [e[2] for e in vc.check(ex, osmo_src)[0] if 'copies the worked example' in e[1]]
        check(fixes and all(x.startswith('Rewrite it about your own topic') for x in fixes),
              f'the fix says to rewrite the copied beat, not delete it: runs5 gutted lessons on "Delete it" ({fixes[:1]})')
        b0["say"] = 'Water moves across the membrane toward the side with more solute.'
        errs = [e[1] for e in vc.check(ex, osmo_src)[0] if e[0].startswith('Scene 1 ') and e[0].endswith('beat 1')]
        check(not any('copies the worked example' in e for e in errs), 'an osmosis sentence in an osmosis lesson is not flagged')
    else:
        check(False, 'the osmosis eval sources are present for the copy test')
    errs = [e[1] for e in vc.check(sky(), srcs)[0]]
    check(not any('copies the worked example' in e for e in errs), 'the worked example itself, checked against its own source, is not flagged')
    two = sky()
    two['claims'][0]['file'] = 'nothing-like-it.md'
    two['claims'][0]['quote'] = 'No given file holds this sentence at all.'
    check(vc.tidy(two, srcs) == [] and two['claims'][0]['file'] == 'nothing-like-it.md', 'a file name close to no given file, with a quote no file holds, is left for the check to report')
    # runs5: a 1.7B named the web page as the file on every claim, and never fixed it from the report.
    for bad_file in ('spaceplace.nasa.gov/blue-sky/en/', None):
        web = sky()
        if bad_file is None:
            web['claims'][0].pop('file')
        else:
            web['claims'][0]['file'] = bad_file
        done_web = vc.tidy(web, srcs)
        check(web['claims'][0].get('file') == sky()['claims'][0]['file'] and any('the one file that holds its quote' in x for x in done_web),
              f'a claim whose file is {bad_file!r} gets the one given file that holds its quote ({done_web})')
    many = {'a.md': srcs[sorted(srcs)[0]], 'b.md': srcs[sorted(srcs)[0]]}
    amb = sky()
    amb['claims'][0]['file'] = 'page.html'
    check(vc.tidy(amb, many) == [] and amb['claims'][0]['file'] == 'page.html', 'a quote found in two given files is left for the learner to name')
    r = run(write('tidy.json', untidy), '--sources', SKY_SRC)
    check('Fixed and saved' in r.stdout and json.loads((WORK / 'tidy.json').read_text())['claims'][1]['from'] == 'outside', f'main() saves the tidied file and says so ({r.stdout.splitlines()[:1]})')

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
    for bad in ({'allele': 5}, ['allele'], {'allele': ''}, 'uh-LEEL'):
        d = sky()
        d['pronounce'] = bad
        expect(f'pronounce {bad!r}', d, 'must map words to respellings', '"pronounce"')
    d = sky()
    d['pronounce'] = {'Rayleigh': 'RAY-lee'}
    clean('pronounce as a map of strings', d)

    # Sentence rules.
    d = sky()
    d['scenes'][2]['beats'][1]['say'] = ' '.join(['word'] * 31) + '.'
    expect('31-word sentence', d, 'says 31 words in one beat', 'Scene 3')
    d = sky()
    d['scenes'][2]['beats'][1]['say'] = ' '.join(['word'] * 30) + '.'
    check(not [e for e in problems(d)[0] if 'words in one beat' in e[1]], 'a 30-word sentence is only a warning')

    d = sky()
    del d['scenes'][2]['beats'][1]['claims']
    expect('fact sentence with no claims', d, 'has no claim ids', 'Scene 3 (Air scatters blue more), beat 2')

    d = sky()
    b = d['scenes'][0]['beats'][0]
    check(b.get('talk') is True, 'fixture: the first beat is a talk beat')
    b['say'] = 'Look up on a clear afternoon at 3 and the sky is blue.'
    expect('talk beat with a digit', d, 'is marked "talk" but has a number in it', 'Scene 1')

    d = sky()
    b = d['scenes'][2]['beats'][1]
    b.setdefault('show', []).append({'type': 'label', 'text': 'knock the light off in all'})
    check(vc.norm('knock the light off in all') in vc.norm(b['say']), 'fixture: the label text is inside the narration')
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
    check('pause' in beat(d, 4, 4), 'fixture: scene 5 ends with a pause')
    stretch(d, 4, 4, 90)
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
    # Regression: the half-screen warning reused the name holding lessonType, so a problem lesson with
    # that layout lost its "has no faded example" error.
    d = sky()
    d['lessonType'] = 'problem'
    d['scenes'][2]['role'] = 'worked'
    d['scenes'][4]['beats'][3].setdefault('show', []).append({'type': 'step', 'text': 'Look up at noon'})
    errs, warns = problems(d)
    check(any('half the screen empty' in w[1] for w in warns), f'fixture: scene 5 leaves half the screen empty ({text_of(warns)})')
    expect('a half-empty screen in a problem lesson with no faded example', d, 'has no faded example', 'The video')

    # Terms in the first two scenes.
    d = sky()
    for s in d['scenes'][:2]:
        for b in s['beats']:
            for i, el in enumerate(b.get('show', [])):
                if el['type'] == 'term':
                    b['show'][i] = {'type': 'label', 'text': el['word']}
    expect('no term in scenes 1 and 2', d, 'name no terms', 'Scenes 1 and 2')

    # --sources: every quote, course or outside, must be in the file its claim names.
    other = write('notes.txt', 'These notes talk about clouds and rain, not about sunlight.')
    both = vc.load_sources([other, SKY_SRC])
    d = sky()
    d['claims'][0].update({'from': 'course', 'where': 'Lecture 2, slide 4', 'file': 'notes.txt'})
    expect('course quote missing from its file', d, 'quote not found in notes.txt', 'Claim c1', sources=both)
    d = sky()
    d['claims'][0]['file'] = 'notes.txt'
    expect('outside quote missing from its file is an error too', d, 'quote not found in notes.txt', 'Claim c1', sources=both)
    d['claims'][0]['file'] = 'missing.txt'
    expect('claim names a file not given', d, "names file 'missing.txt'", 'Claim c1', sources=both)
    course = sky()
    course['claims'][0].update({'from': 'course', 'where': 'Lecture 2, slide 4', 'file': 'notes.txt'})
    r = run(write('course.json', course), '--sources', other, '--sources', SKY_SRC)
    check(r.returncode == 1 and 'quote not found in notes.txt' in r.stdout, f'main() with --sources exits 1 on a missing course quote (exit {r.returncode})')

    # --build.
    bad = sky()
    del bad['recall']
    out = WORK / 'bad.html'
    r = run(write('bad.json', bad), '--build', out)
    check(r.returncode == 1 and not out.exists(), f'--build refuses while there are errors and writes nothing (exit {r.returncode})')
    # Regression (review r2 first-F1): with no second reader the skill builds without --final, and that must work.
    alone = sky()
    out = WORK / 'alone.html'
    r = run(write('alone.json', alone), '--sources', SKY_SRC, '--build', out)
    built = out.read_text() if out.exists() else ''
    check(r.returncode == 0 and out.exists() and 'Explanations not independently reviewed' in built,
          f'a lesson with no review builds with --sources and says the explanations were not reviewed (exit {r.returncode})')
    r = run(write('alone.json', alone), '--final', '--sources', SKY_SRC, '--build', WORK / 'alone-final.html')
    check(r.returncode == 1 and not (WORK / 'alone-final.html').exists(), f'--final still refuses a lesson with no review (exit {r.returncode})')
    good = reviewed(sky())
    good['subtitle'] = 'And why sunsets turn red </script><script>alert(1)</script> <!-- x'
    check(problems(good, SKY_SOURCES, final=True)[0] == [], 'fixture: a subtitle holding </script> is still a clean lesson')
    out = WORK / 'good.html'
    r = run(write('good.json', good), '--final', '--sources', SKY_SRC, '--build', out)
    check(r.returncode == 0 and out.exists(), f'--build writes the page for a clean lesson (exit {r.returncode})')
    page = out.read_text() if out.exists() else ''
    blocks = re.findall(r'<script type="application/json" id="lesson">(.*?)</script>', page, re.S)
    check(len(blocks) == 1, 'the built page has exactly one lesson block')
    try:
        back = json.loads(blocks[0]) if blocks else {}
    except json.JSONDecodeError as exc:
        back = {'error': f'not JSON: {exc}'}
    body = {k: v for k, v in back.items() if k != 'verification'}
    check(body == good, 'the embedded JSON parses back to the same lesson plus its verification block')
    v = back.get('verification') or {}
    check(v.get('by') == 'video_check.py' and v.get('sha256') == vc.sha256_of(back) and v.get('level') == 'checked',
          f'the built page carries the checker\'s signed badge ({v.get("level")}, {str(v.get("sha256"))[:12]})')
    check(blocks and '</script' not in blocks[0].lower() and '<!--' not in blocks[0], 'the embedded JSON holds no raw </script or <!--')
    check(page.count('<script') == (vc.TEMPLATE.read_text().count('<script')), 'the build adds no script tags')
    check(blocks and page.replace(blocks[0], '') == re.sub(r'(<script type="application/json" id="lesson">)(.*?)(</script>)', r'\1\3', vc.TEMPLATE.read_text(), count=1, flags=re.S),
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
    # --audio-plan is read-only: video_voice.py keys clips to the file as written, so a tidy here made every clip stale.
    d = sky()
    d['scenes'][2]['beats'][1]['say'] += ' (c5)'
    path = write('plan-untidy.json', d)
    before = path.read_text()
    r = run(path, '--audio-plan')
    check(r.returncode == 0 and path.read_text() == before, '--audio-plan leaves the lesson file unchanged')
    # The copy check reads the example's source file; an install without it loses the check silently.
    for root in (ROOT, ROOT / 'skills' / 'make-video'):
        check((root / 'examples' / 'video-lesson-sky-source.md').is_file(), f'{root.name}/examples has the sky source the copy check needs')

    # Malformed values a small model writes must give a numbered fix, never a traceback.
    d = sky()
    d['scenes'][2]['beats'][1]['claims'] = [{'id': 'c5'}]
    expect('claim id written as an object', d, 'not an id')
    d = sky()
    qi = next((si, bi, k) for si, s in enumerate(d['scenes']) for bi, b in enumerate(s['beats']) for k, e in enumerate(b.get('show') or []) if e.get('type') == 'quote')
    d['scenes'][qi[0]]['beats'][qi[1]]['show'][qi[2]]['claim'] = ['c7']
    expect('quote claim written as a list', d, 'quote cites')
    d = sky()
    d['claims'][0]['file'] = ['a']
    expect('claim file written as a list', d, '"file" must be one file name', sources={'a': 'x'})
    for bad in ('long', -500, 31, True):
        d = sky()
        d['scenes'][2]['beats'][1]['hold'] = bad
        expect(f'hold {bad!r}', d, '"hold" is')
    for bad in ('[]', json.dumps({**SKY_LESSON, 'scenes': ['oops']})):
        r = run(write('plan-bad.json', bad), '--audio-plan')
        check(r.returncode == 0 and 'Traceback' not in r.stderr, f'--audio-plan does not crash on {bad[:20]!r}')


def quote_match():
    """A quote is matched after undoing PDF and typography noise, and only in the file its claim names."""
    variants = {
        'curly quotes': 'A prism makes a “band” of colors from the Sun’s white light.',
        'a ligature (U+FB01)': 'A prism makes a band of colors from ﬁltered white light.',
        'a soft hyphen': 'A prism makes a band of col­ors from white light.',
        'a PDF line-break hyphen': 'A prism makes a band of colors and an equi-\nlibrium of white light.',
    }
    quotes = {
        'curly quotes': 'A prism makes a "band" of colors from the Sun\'s white light.',
        'a ligature (U+FB01)': 'A prism makes a band of colors from filtered white light.',
        'a soft hyphen': 'A prism makes a band of colors from white light.',
        'a PDF line-break hyphen': 'A prism makes a band of colors and an equilibrium of white light.',
    }
    for name, raw in variants.items():
        book = write('book.txt', 'Chapter 3, page 41.\n\n' + raw + '\n')
        sources = vc.load_sources([SKY_SRC, book])
        d = sky()
        d['claims'][1].update({'quote': quotes[name], 'file': 'book.txt'})
        check(quotes[name] not in raw, f'fixture: the {name} source does not hold the quote character for character')
        clean(f'a quote found only after normalizing {name}', d, sources)
        d['claims'][1]['quote'] = quotes[name].replace('white', 'yellow')
        expect(f'a quote with one word changed ({name})', d, 'quote not found in book.txt', 'Claim c2', sources)
    d = sky()
    del d['claims'][2]['file']
    expect('a claim with no "file" when --sources is given', d, 'does not name its file', 'Claim c3', SKY_SOURCES)
    absent('a claim with no "file" without --sources', d, 'does not name its file')


def timestamps():
    """A "where" timestamp must be within 20 s of the line in a timed transcript that holds the quote."""
    lines = [x for x in TRANSCRIPT.read_text().splitlines() if x.strip()]
    check(len(lines) >= 10 and all(re.match(r'^\[\d+:\d\d\] ', x) for x in lines), f'fixture: the transcript has {len(lines)} timed lines')
    check(len(vc.timed_segments(TRANSCRIPT.read_text())) == len(lines), 'the checker reads every line of the transcript as timed')
    clean('the osmosis lesson with the quote at its own timestamp (1:43)', osmosis(), OSMOSIS_SOURCES)
    for where in ('Lecture video, 1:55', 'Lecture video, 1:30'):
        d = osmosis()
        d['claims'][3]['where'] = where
        clean(f'"where" {where[-4:]} is within 20 s of the quote at 1:43', d, OSMOSIS_SOURCES)
    for where in ('Lecture video, 3:13', 'Lecture video, 0:13'):
        d = osmosis()
        d['claims'][3]['where'] = where
        expect(f'"where" {where[-4:]} is 90 s off the quote at 1:43', d, 'is not within 20 s', 'Claim c5', OSMOSIS_SOURCES)
    # Checker bug, left failing on purpose: quote_near() adds 3 segments past the window, so on a transcript with
    # 13 s lines a "where" up to 46 s before the quoted line still passes (and up to 80 s on 30 s lines).
    d = osmosis()
    d['claims'][3]['where'] = 'Lecture video, 1:03'
    expect('"where" 1:03 is 40 s before the quote at 1:43', d, 'is not within 20 s', 'Claim c5', OSMOSIS_SOURCES)
    # Regression: YouTube WebVTT kept cue settings and word-timing tags, so no multi-word quote matched.
    vtt = write('lecture.vtt', 'WEBVTT\nKind: captions\nLanguage: en\n\n'
                '00:01:40.000 --> 00:01:43.000 align:start position:0%\nWater moves<00:01:41.000><c> across</c><00:01:42.000><c> the membrane.</c>\n\n'
                '00:01:43.000 --> 00:01:46.000 align:start position:0%\nNormal<00:01:43.560><c> saline</c><00:01:44.000><c> is 0.9 percent salt.</c>\n\n'
                '00:01:46.000 --> 00:01:49.000 align:start position:0%\nIt is isotonic to red blood cells.\n')
    vs = vc.load_sources([vtt])
    q = vc.norm('Normal saline is 0.9 percent salt.')
    check(vc.has(vs['lecture.vtt'], q), f'a quote is found in a YouTube .vtt ({vs["lecture.vtt"][:90]})')
    check(vc.quote_near(vs.raw['lecture.vtt'], q, 103) is True and vc.quote_near(vs.raw['lecture.vtt'], q, 200) is False,
          'a .vtt quote is placed at its cue time')


def calcs():
    clean('a calc chain (k1 from literals, k2 from k1)', osmosis(), OSMOSIS_SOURCES)
    d = osmosis()
    d['calc'][0]['value'] = 4.6
    hit = expect('a calc with a wrong value', d, 'says 4.6, but 500 * 0.9 / 100 = 4.5', 'Calc k1', OSMOSIS_SOURCES)
    check(hit and '"value": 4.5' in hit[0][2], 'the fix names the right value')
    d = osmosis()
    d['calc'][1]['value'] = 20
    expect('a wrong value later in the chain', d, 'says 20, but k1 * 4 = 18', 'Calc k2', OSMOSIS_SOURCES)

    def with_calc(**k):
        d = osmosis()
        d['calc'].append({'id': 'k3', **k})
        return d
    absent('"round": 3 with value 0.667 for 2/3', with_calc(expr='2/3', value=0.667, round=3), 'k3', OSMOSIS_SOURCES)
    absent('no "round" with value 0.7 for 2/3 (one decimal written)', with_calc(expr='2/3', value=0.7), 'says 0.7', OSMOSIS_SOURCES)
    expect('"round": 3 is honored: 0.7 is wrong to 3 places', with_calc(expr='2/3', value=0.7, round=3), 'says 0.7, but 2/3 = 0.667', 'Calc k3', OSMOSIS_SOURCES)
    for bad in (9, 'two', -1, True):
        expect(f'"round": {bad!r}', with_calc(expr='2/3', value=0.667, round=bad), '"round" must be a whole number', 'Calc k3', OSMOSIS_SOURCES)
    expect('a bare literal expr', with_calc(expr='42', value=42), 'only restates a number', 'Calc k3', OSMOSIS_SOURCES)
    expect('a negative bare literal expr', with_calc(expr='-42', value=-42), 'only restates a number', 'Calc k3', OSMOSIS_SOURCES)
    marker = WORK / 'pwned'
    attacks = {
        'an __import__ call': (f"__import__('os').system('touch {marker}')", 'something other than numbers'),
        "__import__('os')": ("__import__('os')", 'something other than numbers'),
        'attribute access': ('(1).real', 'something other than numbers'),
        'attribute access on a calc id': ('k1.real', 'something other than numbers'),
        'a lambda': ('(lambda: 1)()', 'something other than numbers'),
        'a string': ("'a' * 3", 'something other than numbers'),
        '2**999': ('2**999', 'a power is too large'),
        'a caret power 10^400': ('10^400', 'a power is too large'),
        'a division by zero': ('1/0', 'divides by zero'),
        'an unknown name': ('zz + 1', "it uses 'zz'"),
        'a later calc id': ('k4 + 1', "it uses 'k4'"),
        'a list comprehension': ('[1 for x in ()]', 'something other than numbers'),
        'unbalanced brackets': ('(1 + 2', 'not arithmetic Python can read'),
    }
    for name, (expr, why) in attacks.items():
        try:
            errors = problems(with_calc(expr=expr, value=1), OSMOSIS_SOURCES)[0]
            crashed = None
        except Exception as exc:  # a traceback is a failure
            errors, crashed = [], exc
        hit = [e for e in errors if e[0] == 'Calc k3' and '"expr" cannot be computed' in e[1] and why in e[1]]
        check(crashed is None and bool(hit), f'expr with {name} is a clean error "{why}" ({crashed or text_of(errors)[:2]})')
    check(not marker.exists(), 'no expr ran code (the marker file was never created)')
    check(vc.safe_eval('sqrt(16) + abs(-2) + 2^3', {}) == 14.0, 'safe_eval does sqrt, abs and ^ as a power')


def numbers():
    def nums(text):
        return [(n[0], n[2]) for n in vc.numbers_in(text)]
    check(nums('eighty four point five') == [(84.5, False)], f'a spelled-out number is read: {nums("eighty four point five")}')
    check(nums('Step 2 and slide 5') == [], f'"Step 2" and "slide 5" are not numbers: {nums("Step 2 and slide 5")}')
    check(nums('x^2') == [], f'the exponent in x^2 is not a number: {nums("x^2")}')
    check(nums('70% of them') == [(70.0, True)], '70% is read as a percent')
    # Regression: ordinal labels matched inside words, so "dropped 37" read as "p 37" and "increased forty" as "ed forty".
    check(nums('it dropped 37 percent') == [(37.0, True)], f'"dropped 37 percent" is a number: {nums("it dropped 37 percent")}')
    check(nums('it increased forty percent') == [(40.0, True)], f'"increased forty percent" is a number: {nums("it increased forty percent")}')
    check(nums('see p. 37 and ch 4') == [], f'"p. 37" and "ch 4" are still labels: {nums("see p. 37 and ch 4")}')

    d = osmosis()
    clean('a number in "say" backed by its cited calc', d, OSMOSIS_SOURCES)
    d['scenes'][2]['beats'][1]['claims'] = ['c5']
    expect('the same number with nothing cited behind it', d, "'four point five', which no cited", 'Scene 3', OSMOSIS_SOURCES)

    d = osmosis()
    beat(d, 0, 1)['say'] = 'Subtract 7 from 19 and you get 12, then divide by 2 to get 6.'
    hit = expect('unbacked numbers in one sentence', d, "'7', '19', '12', '2', '6', which no cited", 'Scene 1', OSMOSIS_SOURCES)
    fix = hit[0][2] if hit else ''
    pasted = [json.loads(x) for x in re.findall(r'\{"id": "k\d+", "expr": "[^"]+", "value": [\d.]+\}', fix)]
    check(len(pasted) >= 1 and 'For ' not in fix and 'to its "claims"' in fix, f'the fix gives calc lines to paste for every number ({fix[:200]})')
    d['calc'] += pasted
    beat(d, 0, 1)['claims'] = beat(d, 0, 1).get('claims', []) + [k['id'] for k in pasted]
    absent('pasting the suggested calcs clears the problem', d, 'which no cited', OSMOSIS_SOURCES)
    beat(d, 0, 1)['say'] = 'The tank holds 37 liters.'
    fix = (expect('a number no arithmetic gives', d, "'37'", 'Scene 1', OSMOSIS_SOURCES) or [('', '', '')])[0][2]
    check('"expr"' in fix and 'cite the claim whose quote has it' in fix and '37' in fix, f'with no arithmetic match the fix says to cite or work an example ({fix[:160]})')
    many = sky()
    for c in many['claims']:
        c['from'] = 'web'
    r = run(write('many.json', many))
    check(re.search(r'^1\. Claim c1; Claim c2.*\(\d+ places\): "from" must be', r.stdout, re.M) is not None,
          f'the same problem in many places is printed once, naming each place ({[l for l in r.stdout.splitlines() if l[:2] == "1."][:1]})')
    lots = sky()
    lots['scenes'][0]['beats'][0]['claims'] = [f'zz{i}' for i in range(15)]
    r = run(write('lots.json', lots))
    shown = len(re.findall(r'^\d+\. ', r.stdout, re.M))
    check(shown == vc.SHOW_MAX and 'more kinds of problem' in r.stdout, f'a long report shows the first {vc.SHOW_MAX} and says more remain (showed {shown})')

    d = osmosis()
    beat(d, 0, 1)['say'] = 'Osmosis moves eighty four point five percent of the water across a selectively permeable membrane.'
    expect('an unbacked spelled-out number', d, "states 'eighty four point five'", 'Scene 1', OSMOSIS_SOURCES)
    beat(d, 0, 1)['say'] = 'Water uptake dropped 37 percent across the membrane.'
    expect('an unbacked number after a word ending in p', d, "'37%'", 'Scene 1', OSMOSIS_SOURCES)

    d = osmosis()
    beat(d, 0, 0)['say'] = 'Look at slide 5 and Step 2 of your notes again.'
    absent('"slide 5" and "Step 2" in a talk beat are not numbers', d, 'has a number in it', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 1, 0)['show'].append({'type': 'equation', 'text': 'x^2 + y^2'})
    absent('an exponent on screen is not a number', d, 'The screen states', OSMOSIS_SOURCES)

    d = osmosis()
    beat(d, 2, 1)['show'][0]['text'] = '500 × 0.9 / 100 = 4.6 g'
    expect('an unbacked number in an equation', d, "The screen states '4.6'", 'Scene 3 (Normal saline), beat 2, show 1', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 0)['show'][1]['cells'] = ['Saline', '7 g']
    expect('an unbacked number in a table row', d, "The screen states '7'", 'Scene 3 (Normal saline), beat 1, show 2', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 0)['show'] = [{'type': 'table', 'columns': ['Bag', 'Salt'], 'rows': [['Saline', '7 g']]}]
    expect('an unbacked number in a table cell', d, "The screen states '7'", 'Scene 3 (Normal saline), beat 1, show 1', OSMOSIS_SOURCES)
    # Regression: backs() once checked a percent's fraction (0.8% -> 0.008) at the percent's own decimals and let
    # any non-whole pool number within 0.5 back a whole percent, so 0.8% passed on the 0.009 from "0.9 percent".
    d = osmosis()
    beat(d, 2, 0)['show'][1]['cells'] = ['Saline', '0.8%']
    expect('0.8% in a table row backed only by "0.9 percent"', d, "The screen states '0.8%'", 'Scene 3', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 1)['show'].append({'type': 'bars', 'title': 'Salt per bag', 'items': [{'label': 'one', 'value': 4.5}, {'label': 'four', 'value': 19}]})
    expect('an unbacked bars value', d, "The screen states '19'", 'Scene 3 (Normal saline), beat 2, show 2', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 2)['show'] = [{'type': 'bars', 'title': 'Salt per bag', 'items': [{'label': 'one', 'value': 4.5}, {'label': 'four', 'value': 18}]}]
    absent('bars values backed by the beat\'s calc', d, 'The screen states', OSMOSIS_SOURCES)

    def with_fraction(say, expr='14 / 20', value=0.7):
        d = osmosis()
        d['calc'].append({'id': 'k3', 'expr': expr, 'value': value})
        d['scenes'][2]['beats'].insert(3, {'say': say, 'claims': ['k3']})
        return d
    clean('70% backed by a calc of 0.7', with_fraction('Fourteen of twenty cells shrank, so 70% shrank.'), OSMOSIS_SOURCES)
    expect('7% is not backed by 0.7', with_fraction('Fourteen of twenty cells shrank, so 7% shrank.'), "states '7%'", 'Scene 3', OSMOSIS_SOURCES)
    expect('75% is not backed by 0.7', with_fraction('Fourteen of twenty cells shrank, so 75% shrank.'),
           "states '75%'", 'Scene 3', OSMOSIS_SOURCES)
    clean('0.844 said for 0.84439', with_fraction('The share of cells that shrank is 0.844.', '84.439 / 100', 0.84439), OSMOSIS_SOURCES)
    expect('0.85 said for 0.84439', with_fraction('The share of cells that shrank is 0.85.', '84.439 / 100', 0.84439), "states '0.85'", 'Scene 3', OSMOSIS_SOURCES)


def exact_marks():
    """A sign, an inequality, a Greek letter or a decimal point changes a fact, so a quote that differs in one is
    not found, and small spelled numbers in worked arithmetic must be backed like digits."""
    # Regression (review r1b sol-F2, second-N2): norm() kept only a-z and 0-9, so each pair below matched.
    for name, source, quote in (
            ('a flipped sign', 'At night the surface drops to -30.5 degrees on the far side.', 'At night the surface drops to 30.5 degrees on the far side.'),
            ('a minus sign (U+2212)', 'The charge on the ion is −2 in this salt.', 'The charge on the ion is 2 in this salt.'),
            ('a flipped inequality', 'We reject the null when p < 0.05 in this course.', 'We reject the null when p > 0.05 in this course.'),
            ('a flipped ≤', 'The dose stays ≤ 10 milligrams per kilogram each day.', 'The dose stays ≥ 10 milligrams per kilogram each day.'),
            ('a swapped Greek letter', 'The α level for this test is set at 0.05 by convention.', 'The β level for this test is set at 0.05 by convention.'),
            ('an exponent read as digits', 'Avogadro gives about 6.02 × 10²³ particles per mole.', 'Avogadro gives about 6.02 × 1023 particles per mole.'),
            ('a decimal read as thousands', 'The pond held 1.500 liters of water that morning.', 'The pond held 1,500 liters of water that morning.'),
            # Regression (review r2 sol-F2): + * / and a spaced minus were dropped, so x + y matched x / y.
            ('addition read as division', 'For this rule, x + y = 10 in every case.', 'For this rule, x / y = 10 in every case.'),
            ('subtraction read as multiplication', 'For this rule, x - y = 10 in every case.', 'For this rule, x * y = 10 in every case.'),
            ('a times sign dropped', 'The area is 3 \u00d7 4 square meters here.', 'The area is 34 square meters here.'),
            ('a division sign dropped', 'The ratio is 12 \u00f7 4 for this mix.', 'The ratio is 12 4 for this mix.')):
        check(not vc.has(vc.norm(source), vc.norm(quote)), f'a quote with {name} is not found in the source ({vc.norm(quote)!r} in {vc.norm(source)!r})')
        check(vc.has(vc.norm(source), vc.norm(source.split(' ', 1)[1])), f'the unchanged quote is still found ({name})')
    check(vc.has(vc.norm('A herd of 1,500 frogs lived there.'), vc.norm('A herd of 1500 frogs lived there.')), 'a thousands comma is optional in a quote')
    check(vc.norm('µm') == vc.norm('μm'), 'the micro sign and Greek mu read the same')
    check(vc.norm('The area is 3 \u00d7 4 here.') == vc.norm('The area is 3 * 4 here.'), 'a times sign reads as *')
    check(vc.has(vc.norm('A well-known rule of thumb holds.'), vc.norm('A well known rule of thumb holds.')), 'a hyphen inside a word is not a minus')

    def nums(text, small=False):
        return [n[0] for n in vc.numbers_in(text, small=small)]
    check(nums('it fell to -5 degrees') == [-5.0], f'a minus sign is kept: {nums("it fell to -5 degrees")}')
    check(nums('it fell to −5 degrees') == [-5.0], 'a typographic minus sign is kept')
    check(nums('it fell to negative fifty degrees') == [-50.0], f'"negative" before a spelled number is kept: {nums("it fell to negative fifty degrees")}')
    check(nums('from 5-10 cells') == [5.0, 10.0], f'a hyphen in a range is not a sign: {nums("from 5-10 cells")}')
    # Regression (review r1b first-F1): spelled numbers under 11 were never read, so "divide by three" slipped through.
    check(nums('then divide by three', small=True) == [3.0], f'small=True reads "three": {nums("then divide by three", small=True)}')
    check(nums('then divide by three') == [], 'small=False leaves "three" to narration')
    check(nums('one of the bags', small=True) == [], 'a lone "one" is not a number')
    check(nums('multiply by one', small=True) == [1.0], '"one" after a math word is a number')
    check(nums("the four o'clock plants", small=True) == [], "\"four o'clock\" is a name or a time, not a count")

    d = osmosis()
    d['claims'][3]['text'] = 'Normal saline is -0.9 percent salt and isotonic to red blood cells.'
    beat(d, 2, 0)['say'] = 'Normal saline is negative zero point nine percent salt, and it is isotonic to red blood cells.'
    expect('a sentence that flips the sign of its quoted number', d, "states 'negative zero point nine'", 'Scene 3', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 2)['say'] = 'Four of those bags hold eighteen grams, so three bags would hold the rest.'
    expect('an unbacked small number in a beat that cites a calc', d, "states 'three'", 'Scene 3 (Normal saline), beat 3', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 1, 0)['say'] = 'In a hypertonic solution, water leaves the cell and it shrinks, one way only.'
    absent('a small spelled number in a plain sentence is narration', d, "states 'one'", OSMOSIS_SOURCES)
    # Regression (review r2 second-S1): a fact sentence saying "three" against a quote saying "four" passed.
    heart = write('heart.md', 'The human heart has four chambers, two atria and two ventricles.')
    srcs = vc.load_sources([OSMOSIS_DIR, TRANSCRIPT, heart])
    d = osmosis()
    d['claims'].append(claim('c6', 'The heart has four chambers.', 'heart.md', 'Notes, heart', 'The human heart has four chambers, two atria and two ventricles.'))
    d['scenes'][1]['beats'].insert(1, {'say': 'The human heart has three chambers.', 'claims': ['c6']})
    expect('a small spelled number that contradicts its quote', d, "states 'three', which no cited", 'Scene 2', srcs)
    d['scenes'][1]['beats'][1]['say'] = 'The human heart has four chambers.'
    absent('the small spelled number its quote gives', d, 'which no cited', srcs)
    d = osmosis()
    beat(d, 2, 3)['pause']['ask'] = 'Add the salt in the four bags, then say the total. How many grams is that?'
    absent('a small number that counts the task in a pause question', d, 'The pause states', OSMOSIS_SOURCES)
    beat(d, 2, 3)['pause']['why'] = 'Each bag holds four point five grams, and three bags hold the rest.'
    expect('an unbacked small number in a pause\'s why', d, "The pause states 'three'", 'Scene 3 (Normal saline), beat 4', OSMOSIS_SOURCES)


def coverage():
    d = osmosis()
    beat(d, 0, 1)['claims'] = ['c5']
    expect('a claim cited on a sentence that shares none of its key words', d, 'cites c5, but shares no key word', 'Scene 1', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 0, 1)['claims'] = ['c1', 'k1']
    expect('a calc cited on a sentence with none of its numbers', d, 'cites calc k1, but says none of its numbers', 'Scene 1', OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 2, 3)['pause']['claims'] = ['k1', 'k2', 'c1']
    expect('a claim cited on a pause it has nothing to do with', d, 'cites c1, but shares no key word', 'Scene 3', OSMOSIS_SOURCES)


def symbols():
    for sym, say in (('^', 'The area of the cell grows as p^2 grows.'), ('=', 'Hypertonic = more solute outside the cell.')):
        d = osmosis()
        beat(d, 1, 0)['say'] = say
        hit = expect(f'"say" holding {sym!r}', d, f'asks the voice to read the symbol {sym!r}', 'Scene 2', OSMOSIS_SOURCES)
        check(hit and 'Write it the way you would say it' in hit[0][2], f'the fix for {sym!r} says "Write it the way you would say it"')


def conflicts():
    d = osmosis()
    d['claims'] = [c for c in d['claims'] if c['id'] != 'c3']
    beat(d, 1, 1)['claims'] = ['c2']
    beat(d, 1, 1)['say'] = 'So in a hypertonic solution, water leaves the cell and it shrinks.'
    hit = expect('the notes\' sentence used without flagging slide 5', d, 'is contradicted by bio101-slides.md', 'Claim c2', OSMOSIS_SOURCES)
    check(hit and 'gains water and swells' in hit[0][1], 'the conflict error quotes the slide 5 sentence')
    clean('slide 5 recorded as a conflict and a beat citing both', osmosis(), OSMOSIS_SOURCES)
    d = osmosis()
    beat(d, 1, 1)['claims'] = ['c3']
    expect('a conflict pair that no beat cites together', d, 'disagrees with c2, but no beat cites both', 'Claim c3', OSMOSIS_SOURCES)
    d = osmosis()
    del d['claims'][2]['note']
    expect('a conflict with no note', d, 'is marked conflict with no note', 'Claim c3', OSMOSIS_SOURCES)
    d = osmosis()
    d['claims'][2]['other'] = 'c9'
    expect('a conflict naming a claim that does not exist', d, "\"other\" names 'c9'", 'Claim c3', OSMOSIS_SOURCES)
    # The hypotonic slide reads as the opposite of the wrong slide 5. notConflict lets the writer dismiss it, visibly.
    d = osmosis()
    d['claims'].append(claim('c4', 'In a hypotonic solution, water enters the cell.', 'bio101-slides.md', 'Slide 6',
                             'In a hypotonic solution, water enters the cell.'))
    d['scenes'][1]['beats'].append({'say': 'In a hypotonic solution, water enters the cell.', 'claims': ['c4']})
    expect('the hypotonic slide against the wrong slide 5', d, 'is contradicted by bio101-slides.md', 'Claim c4', OSMOSIS_SOURCES)
    # It also reads as the opposite of the notes' "Water leaves the cell and it shrinks." taken alone (a false alarm).
    d['claims'][-1]['notConflict'] = [SLIDE5, 'Water leaves the cell and it shrinks.']
    clean('notConflict dismisses both', d, OSMOSIS_SOURCES)
    lines = badge(d, OSMOSIS_SOURCES)['lines']
    check(any(re.match(r'\d+ possible contradictions? dismissed by the writer', x) for x in lines), f'the badge lines report the dismissal ({lines})')
    d['claims'][-1]['notConflict'] = ['Water leaves the cell and it shrinks.']
    expect('a notConflict that names only one sentence leaves the other flagged', d, 'is contradicted by bio101-slides.md', 'Claim c4', OSMOSIS_SOURCES)
    # Regression: any substring dismissed a conflict, so "e" or "the" silenced the planted-slide attack.
    for tiny in ('e', 'the', 'water'):
        d['claims'][-1]['notConflict'] = [tiny]
        expect(f'notConflict {tiny!r} is too short', d, 'under 5 words', 'Claim c4', OSMOSIS_SOURCES)
        expect(f'notConflict {tiny!r} dismisses nothing', d, 'is contradicted by bio101-slides.md', 'Claim c4', OSMOSIS_SOURCES)
    check(not any('dismissed' in x for x in badge(osmosis(), OSMOSIS_SOURCES)['lines']), 'with nothing dismissed the badge says nothing about it')


def short_quotes():
    # Regression: a two-word real fragment backed any claim text and counted as quoted.
    d = osmosis()
    d['claims'][0]['quote'] = ' '.join(d['claims'][0]['quote'].split()[:2])
    expect('a two-word quote', d, 'too short to show the source states the claim', 'Claim c1', OSMOSIS_SOURCES)
    d = osmosis()
    d['claims'][0]['text'] = 'Blue light is ultraviolet radiation.'
    expect('a real quote under an unrelated claim', d, 'shares no key word with the claim', 'Claim c1', OSMOSIS_SOURCES)
    check(vc.key_terms('The heterozygote share is 2pq, 0.42.') & vc.key_terms("That's why it's 2pq, 0.42."),
          'a quote and claim that share a number or formula (2pq, 0.42) are about the same thing')


def reveal_after_pause():
    # Regression: tidy moved a show-only reveal back into the beat before its pause, so the answer showed first.
    d = sky()
    si, bi = next((si, bi) for si, sc in enumerate(d['scenes']) for bi, b in enumerate(sc['beats']) if 'pause' in b)
    d['scenes'][si]['beats'].insert(bi + 1, {'show': [{'type': 'label', 'text': 'Answer shown'}]})
    vc.tidy(d)
    early = [b for b in d['scenes'][si]['beats'][:bi + 1] if any(e.get('text') == 'Answer shown' for e in b.get('show') or [])]
    check(not early, f'a reveal after a pause stays after it (scene {si + 1}, beat {bi + 1})')


def badges():
    v = badge(sky())
    check(v['level'] == 'unverified' and v['label'].startswith('Unverified'), f'(a) no sources: unverified ({v["level"]}: {v["label"]})')
    v = badge(osmosis(), OSMOSIS_SOURCES)
    check(v['level'] == 'checked' and v['label'] == 'Checked against your course: 4 of 4 claims quoted', f'(b) course lesson, all quoted ({v["level"]}: {v["label"]})')
    check('Explanations not independently reviewed' in v['lines'], '(d) no review: "Explanations not independently reviewed"')
    check(all(x == 'quoted' for x in v['claims'].values()) and len(v['claims']) == 4, 'every claim is listed as quoted')

    d = osmosis()
    openstax = write('openstax.txt', 'Red blood cells have no cell wall, so they can burst in pure water.')
    d['claims'].append({'id': 'c6', 'text': 'Red blood cells have no cell wall, so they can burst.', 'from': 'outside',
                        'where': 'https://openstax.org/books/biology-2e/pages/5-2-passive-transport', 'source': 'OpenStax Biology 2e',
                        'checked': '2026-11-22', 'file': 'openstax.txt',
                        'quote': 'Red blood cells have no cell wall, so they can burst in pure water.'})
    d['scenes'][1]['beats'].insert(1, {'say': 'A red blood cell has no cell wall, so it can burst.', 'claims': ['c6']})
    srcs = vc.load_sources([OSMOSIS_DIR, TRANSCRIPT, openstax])
    clean('fixture: the course lesson with one outside claim', d, srcs)
    v = badge(d, srcs)
    check(v['level'] == 'partial' and v['label'] == 'Checked against your course: 4 of 4 course claims quoted', f'(c) an outside claim makes it partial ({v["level"]}: {v["label"]})')
    check('Not checked against your course: 1 claim from outside sources' in v['lines'], f'(c) the "Not checked against your course" line ({v["lines"]})')

    # Regression (review r1b second-N1): a source the assistant typed itself made its own quotes "checked".
    notes = (OSMOSIS_DIR / 'my-notes.md').read_text()
    typed = write('typed-my-notes.md', notes)
    d = osmosis()
    d['claims'][1]['file'] = 'typed-my-notes.md'
    srcs = vc.load_sources([OSMOSIS_DIR / 'bio101-slides.md', TRANSCRIPT, typed])
    clean('fixture: a course lesson quoting a typed copy of the notes', d, srcs)
    v = badge(d, srcs)
    check(v['level'] == 'partial', f'a quote matched only in a typed- file makes the badge partial ({v["level"]}: {v["label"]})')
    check('1 claim matched only against text the assistant typed, not the original' in v['lines'], f'the badge says which claims rest on typing ({v["lines"]})')

    d = reviewed(osmosis())
    v = badge(d, OSMOSIS_SOURCES)
    check('Explanations reviewed by test (as recorded)' in v['lines'] and 'Explanations not independently reviewed' not in v['lines'],
          f'(d) a recorded review: "Explanations reviewed by" ({v["lines"]})')
    clean('the reviewed osmosis lesson with --final', d, OSMOSIS_SOURCES, final=True)

    # --write signs the file; the signature covers every byte of the lesson.
    path = write('osmosis.json', d)
    r = run(path, '--sources', OSMOSIS_DIR, '--sources', TRANSCRIPT, '--write')
    signed = json.loads(path.read_text())
    sv = signed.get('verification') or {}
    check(r.returncode == 0 and sv.get('by') == 'video_check.py' and sv.get('sha256') == vc.sha256_of(signed),
          f'--write signs the file in place (exit {r.returncode}, {sv.get("level")})')
    check(sv.get('label') == 'Checked against your course: 4 of 4 claims quoted', f'the signed label is the checker\'s ({sv.get("label")})')
    absent('rerunning the checker on the signed file', signed, '"verification"', OSMOSIS_SOURCES)
    r = run(path, '--sources', OSMOSIS_DIR, '--sources', TRANSCRIPT, '--final')
    check(r.returncode == 0, f'main() passes the signed file (exit {r.returncode})')
    edited = copy.deepcopy(signed)
    beat(edited, 0, 1)['say'] = beat(edited, 0, 1)['say'].replace('water', 'wafer', 1)
    expect('one character of "say" edited after signing', edited, 'was not written by the checker for this exact file', '"verification"', OSMOSIS_SOURCES)
    # The hash has no key. A hand-made "checked" block with a correct hash still fails once the sources are given.
    d = osmosis()
    d['claims'][0]['quote'] = 'A sentence that no slide ever says about water.'
    honest = badge(d, OSMOSIS_SOURCES)
    check(honest['level'] != 'checked', f'fixture: an unmatched quote is not checked ({honest["level"]})')
    forged = vc.sign(d, {**honest, 'level': 'checked', 'label': 'Checked against your course: 4 of 4 claims quoted',
                         'claims': {k: 'quoted' for k in honest['claims']}})
    check(forged['verification']['sha256'] == vc.sha256_of(forged), 'fixture: the forged block carries a matching hash')
    expect('a hand-made "checked" block with a matching hash', forged, 'other than this check finds', '"verification"', OSMOSIS_SOURCES)
    forged = osmosis()
    forged['verification'] = {'by': 'video_check.py', 'level': 'checked', 'label': 'Checked', 'sha256': '0' * 64}
    expect('a hand-written verification block', forged, 'was not written by the checker', '"verification"', OSMOSIS_SOURCES)
    forged['verification']['by'] = 'claude'
    forged['verification']['sha256'] = vc.sha256_of(forged)
    expect('a verification block with the right hash but another signer', forged, 'was not written by the checker', '"verification"', OSMOSIS_SOURCES)
    d = osmosis()
    d['learner']['checked'] = 'yes'
    expect('learner.checked "yes"', d, 'a lesson cannot mark itself checked', 'learner.checked', OSMOSIS_SOURCES)

    a = osmosis()
    b = copy.deepcopy(a)
    b['verification'] = {'by': 'anyone', 'level': 'partial', 'sha256': 'x'}
    c = copy.deepcopy(b)
    c['verification']['sha256'] = 'y'
    check(vc.sha256_of(b) == vc.sha256_of(c), 'sha256_of ignores only the hash field itself')
    c['verification']['level'] = 'checked'
    check(vc.sha256_of(b) != vc.sha256_of(c), 'sha256_of covers the badge level, so promoting it breaks the hash')
    # Regression (review r1b sol-F1): the hash left the whole verification block out, so an unverified lesson
    # could be promoted to "checked" by editing level and label alone, and the player showed it.
    low = vc.sign(osmosis(), badge(osmosis()))
    check(low['verification']['level'] == 'unverified', f'fixture: signed with no sources is unverified ({low["verification"]["level"]})')
    low['verification'].update(level='checked', label='Checked against your course: 4 of 4 claims quoted')
    expect('a signed badge promoted by hand, no sources given', low, 'was not written by the checker', '"verification"')
    b = copy.deepcopy(a)
    b['calc'][1]['value'] = 18.0
    b['wpm'] = 145.0
    check(vc.sha256_of(a) == vc.sha256_of(b), 'sha256_of treats 18.0 and 18 the same')
    b['wpm'] = 146
    check(vc.sha256_of(a) != vc.sha256_of(b), 'sha256_of changes when a value changes')


def pause_and_length():
    d = osmosis()
    beat(d, 2, 2)['show'] = [{'type': 'label', 'text': '18 grams'}]
    expect('the pause answer on screen earlier in the scene', d, 'which is already on screen in this scene', 'Scene 3 (Normal saline), beat 4', OSMOSIS_SOURCES)
    d = osmosis()
    d['scenes'][2]['beats'].append({'say': 'So four bags hold eighteen grams of salt.', 'claims': ['k2'],
                                     'show': [{'type': 'label', 'text': '18 grams'}]})
    clean('the same answer shown after the pause', d, OSMOSIS_SOURCES)

    d = sky()
    stretch(d, 2, 1, 200)
    stretch(d, 4, 1, 200)
    hit = expect('over 6.5 minutes of narration', d, 'minutes of narration', 'The video')
    check(hit and '"part"' in hit[0][2], 'the length fix says to split it into parts with "part"')
    d = sky()
    stretch(d, 4, 1, 60)
    absent('a video under 6.5 minutes', d, 'minutes of narration')

    # Time follows words as spoken, and recorded clips when there are any.
    for text, n in (('Step 2: p squared is 0.4225, 2 p q is 0.455.', 20), ('Carriers are 50,000 times 2 p q, about 990.', 12),
                    ('40% of .5', 6), ('The sky is blue.', 4)):
        check(vc.spoken_words(text) == n, f'spoken words: {text!r} is {n} words aloud ({vc.spoken_words(text)})')

    def voiced(lesson, factor=None, fixed=None):
        lines = [b['say'] for b in say_beats(lesson)]
        secs = {vc.fnv1a(t): fixed if fixed is not None else round(vc.spoken_words(t) * 60 / lesson['wpm'] * factor, 2) for t in lines}
        lesson['audio'] = {'clips': {k: f'audio/{k}.mp3' for k in secs}, 'seconds': secs,
                           'voice': {'engine': 'cmd', 'name': 'v', 'disclose': 'Narration is an AI voice: test (v).'}}
        return lesson
    absent('recorded clips at the lesson pace', voiced(stretch(sky(), 4, 1, 60), 1.0), 'minutes of narration')
    expect('recorded clips three times as long as the estimate push it past 6.5 minutes', voiced(stretch(sky(), 4, 1, 60), 3.0),
           'minutes of narration', 'The video')
    d = voiced(sky(), 1.0)
    d['audio']['seconds'][vc.fnv1a(say_beats(d)[1]['say'])] = 0.2
    expect('a clip length too short for its sentence', d, 'do not fit their sentence', '"audio.seconds"')
    expect('"audio.seconds" that is not a map', voiced(sky(), fixed='long'), 'do not fit their sentence', '"audio.seconds"')
    for bad in ({'n': 3, 'of': 2, 'series': 'Sky'}, {'n': 0, 'of': 2}, {'n': 1, 'of': 13}, {'n': '1', 'of': 2}, [1, 2]):
        d = sky()
        d['part'] = bad
        expect(f'"part" {bad!r}', d, 'must be {"n": 1', '"part"')
    d = sky()
    d['part'] = {'n': 1, 'of': 2, 'series': 'Light and color'}
    clean('"part" 1 of 2', d)


def show_types():
    def add(lesson, el, si=1, bi=0):
        beat(lesson, si, bi).setdefault('show', []).append(el)
        return lesson
    expect('a table with a short row', add(osmosis(), {'type': 'table', 'columns': ['Beaker', 'Cell'], 'rows': [['Hypertonic']]}),
           'table "rows" must be up to 6 rows of 2 cells each', 'Scene 2', OSMOSIS_SOURCES)
    expect('a table with one column', add(osmosis(), {'type': 'table', 'columns': ['Beaker'], 'rows': []}),
           'table "columns" must list 2 to 5 headings', 'Scene 2', OSMOSIS_SOURCES)
    expect('a row with no table before it in the scene', add(osmosis(), {'type': 'row', 'cells': ['Hypertonic', 'shrinks']}),
           'no table is on screen in this scene', 'Scene 2', OSMOSIS_SOURCES)
    d = osmosis()
    d['scenes'][2]['beats'].append({'say': 'Normal saline is isotonic to red blood cells.', 'claims': ['c5'],
                                     'show': [{'type': 'row', 'cells': ['Saline', 'isotonic', 'extra']}]})
    expect('a row wider than its table', d, 'row must have 2 cells', 'Scene 3', OSMOSIS_SOURCES)
    d = osmosis()
    d['scenes'][2]['beats'].append({'say': 'Normal saline is isotonic to red blood cells.', 'claims': ['c5'],
                                     'show': [{'type': 'row', 'cells': ['Red cell', 'keeps shape']}]})
    clean('a valid table plus two rows', d, OSMOSIS_SOURCES)
    for bad in (-2, 'lots', True):
        expect(f'bars with value {bad!r}', add(osmosis(), {'type': 'bars', 'items': [{'label': 'a', 'value': 1}, {'label': 'b', 'value': bad}], 'claims': ['c2']}),
               'bars "items" must be 2 to 6', 'Scene 2', OSMOSIS_SOURCES)
    expect('bars with one item', add(osmosis(), {'type': 'bars', 'items': [{'label': 'a', 'value': 0}], 'claims': ['c2']}),
           'bars "items" must be 2 to 6', 'Scene 2', OSMOSIS_SOURCES)
    expect('a term with tier "core"', add(osmosis(), {'type': 'term', 'word': 'Solute', 'meaning': 'What is dissolved', 'tier': 'core'}),
           '"tier" is \'core\'', 'Scene 2', OSMOSIS_SOURCES)
    expect('tier on a compare', add(osmosis(), {'type': 'compare', 'left': 'Hyper', 'right': 'Hypo', 'leftItems': ['shrinks'], 'rightItems': ['swells'], 'tier': 'given'}),
           'a compare cannot have "tier"', 'Scene 2', OSMOSIS_SOURCES)
    for tier in ('memorize', 'given'):
        absent(f'a term with tier {tier!r}', add(osmosis(), {'type': 'term', 'word': 'Solute', 'meaning': 'What is dissolved', 'tier': tier}), 'tier', OSMOSIS_SOURCES)

    # Regression (review r1b sol-F3): graph points were checked for shape only, so invented data passed.
    def graph(points, mark=None):
        el = {'type': 'graph', 'title': 'Salt by bags', 'x': 'Bags', 'y': 'Grams', 'points': points, 'claims': ['k1', 'k2']}
        if mark:
            el['mark'] = mark
        return add(osmosis(), el, 2, 2)
    expect('a graph of invented points', graph([[0, 123456], [1, 987654]]), 'graph value(s) 123456, 987654 come from no cited quote or calc',
           'Scene 3 (Normal saline), beat 3, show 1', OSMOSIS_SOURCES)
    absent('a graph whose y values are its calcs, on a counting x axis', graph([[1, 4.5], [2, 18]]), 'graph value', OSMOSIS_SOURCES)
    absent('a graph whose x values come from its calcs', graph([[500, 4.5], [4, 18]]), 'graph value', OSMOSIS_SOURCES)
    expect('a graph with one point changed', graph([[1, 4.5], [2, 19]]), 'graph value(s) 19 come', 'Scene 3', OSMOSIS_SOURCES)
    expect('a graph whose x values are not a count and not backed', graph([[3, 4.5], [7, 18]]), 'graph value(s) 3, 7 come', 'Scene 3', OSMOSIS_SOURCES)
    expect('a graph mark at an invented value', graph([[1, 4.5], [2, 18]], {'x': 2, 'y': 25, 'label': 'four bags'}),
           'graph value(s) 25 come', 'Scene 3', OSMOSIS_SOURCES)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
