#!/usr/bin/env python3
"""Attack a lesson that scripts/video_check.py passes, and report which attacks the checker catches.

    python3 evals/make-video/attacks.py LESSON.json --sources DIR [--sources FILE ...] [--out table.md]
    python3 evals/make-video/attacks.py --self-test

Each attack is one mistake a small model makes, applied to a fresh copy of the lesson in the first place it fits:

  1. invented quote: one claim's quote replaced by a sentence that is not in the sources;
  2. arithmetic slip: one calc's value off by one in its last digit (or, with no calcs, a backed number in the
     narration changed to a nearby wrong one);
  3. uncited number: "in about 37 percent of cases" added to a fact sentence;
  4. citation on an unrelated sentence: a claim id cited on a beat about something else;
  5. planted slide error presented silently: the correct hypertonic claim swapped for slide 5's wrong sentence,
     with the conflict flag removed (osmosis sources only);
  6. self-set "checked" badge: a hand-written verification block, and separately learner.checked = "yes";
  7. misquoted video timestamp: a transcript claim's "where" moved 90 s.

The checker must catch each one with an error. The table names the first error and the gate that raised it.
--self-test runs all seven on a built-in osmosis lesson with a timed lecture transcript and exits 1 unless every
attack is caught.
"""
import argparse
import copy
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / 'scripts' / 'video_check.py'
OSMOSIS = ROOT / 'evals' / 'make-video' / 'sources' / 'osmosis'
SLIDE5 = 'In a hypertonic solution, the cell gains water and swells.'
UNCITED = 'in about 37 percent of cases'
SHIFT = 90  # seconds a timestamp is moved

_spec = importlib.util.spec_from_file_location('video_check', CHECKER)
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

# Which gate raised an error, read from its wording.
GATES = [
    ('quote not found in', 'quote match'),
    ('does not name its file', 'quote match'),
    ('which was not given to --sources', 'quote match'),
    ('is not within', 'transcript timestamp'),
    ('"expr" cannot be computed', 'calc recompute'),
    ('only restates a number', 'calc recompute'),
    ('which no cited quote or calc gives', 'numbers backed'),
    ('shares no key word', 'coverage'),
    ('says none of its numbers', 'coverage'),
    ('is contradicted by', 'conflict sweep'),
    ('no beat cites both', 'conflict pair'),
    ('was not written by the checker', 'signature'),
    ('cannot mark itself checked', 'learner.checked'),
    ('asks the voice to read the symbol', 'symbols read aloud'),
]


def gate_of(problem):
    if re.match(r'says .*, but .* = ', problem):
        return 'calc recompute'
    for text, gate in GATES:
        if text in problem:
            return gate
    return 'other'


def say_beats(lesson):
    """(scene index, beat index, beat) for every narration beat."""
    for si, scene in enumerate(lesson.get('scenes') or []):
        for bi, beat in enumerate(scene.get('beats') or [] if isinstance(scene, dict) else []):
            if isinstance(beat, dict) and isinstance(beat.get('say'), str):
                yield si, bi, beat


def fact_beats(lesson):
    return [(si, bi, b) for si, bi, b in say_beats(lesson) if b.get('talk') is not True and b.get('claims')]


def claims_of(lesson):
    return [c for c in lesson.get('claims') or [] if isinstance(c, dict) and c.get('id')]


def label(si, bi):
    return f'scene {si + 1}, beat {bi + 1}'


# ---------------------------------------------------------------- the attacks
# Each takes (lesson, sources) and returns (attacked lessons, where it was applied) or (None, why not applicable).

def invented_quote(lesson, sources):
    for c in claims_of(lesson):
        fname = c.get('file')
        if not c.get('quote') or fname not in sources:
            continue
        fake = str(c.get('text', '')).strip() or 'This fact appears in the course materials.'
        if vc.has(sources[fname], vc.norm(fake)):
            fake = fake.rstrip('.') + ' in every case.'
        d = copy.deepcopy(lesson)
        next(x for x in claims_of(d) if x['id'] == c['id'])['quote'] = fake
        return [d], f'claim {c["id"]} quote set to its own paraphrase'
    return None, 'no claim names a file given to --sources'


def _bump(value):
    """A plausible slip: one more in the last written digit."""
    s = repr(float(value))
    dec = len(s.split('.')[1]) if '.' in s and not s.endswith('.0') else 0
    return round(value + 10 ** -dec, dec) if dec else int(value) + 1


def arithmetic_slip(lesson, sources):
    calc = [k for k in lesson.get('calc') or [] if isinstance(k, dict) and isinstance(k.get('value'), (int, float))]
    if calc:
        d = copy.deepcopy(lesson)
        k = next(x for x in d['calc'] if isinstance(x, dict) and x.get('id') == calc[0].get('id'))
        old = k['value']
        k['value'] = _bump(old)
        return [d], f'calc {k.get("id")} value {old} -> {k["value"]}'
    for si, bi, beat in fact_beats(lesson):
        for value, dec, pct, _, shown in vc.numbers_in(beat['say']):
            words = shown[:-1] if shown.endswith('%') else shown
            m = re.search(r'(?<![\w.])' + r'[\s-]+'.join(map(re.escape, words.split())) + r'(?![\w])', beat['say'], re.I)
            if not m:
                continue
            wrong = f'{value + 10 ** -dec:.{dec}f}' if dec else str(int(value) + 1)
            d = copy.deepcopy(lesson)
            b = d['scenes'][si]['beats'][bi]
            b['say'] = b['say'][:m.start()] + wrong + b['say'][m.end():]
            return [d], f'{label(si, bi)}: "{m.group(0)}" -> {wrong}'
    return None, 'no calcs and no number in the narration'


def uncited_number(lesson, sources):
    for si, bi, beat in fact_beats(lesson):
        if vc.numbers_in(beat['say']):
            continue
        d = copy.deepcopy(lesson)
        b = d['scenes'][si]['beats'][bi]
        b['say'] = b['say'].rstrip().rstrip('.!?') + ', ' + UNCITED + '.'
        return [d], f'{label(si, bi)}: added "{UNCITED}"'
    return None, 'no fact sentence without a number'


def unrelated_citation(lesson, sources):
    claims = claims_of(lesson)
    for si, bi, beat in fact_beats(lesson):
        if vc.numbers_in(beat['say']):
            continue
        said = vc.stems(beat['say'])
        for c in claims:
            if c['id'] in beat['claims'] or c.get('status') == 'conflict':
                continue
            if said & (vc.stems(c.get('quote', '')) | vc.stems(c.get('text', ''))):
                continue
            d = copy.deepcopy(lesson)
            d['scenes'][si]['beats'][bi]['claims'] = [c['id']]
            return [d], f'{label(si, bi)}: cites {c["id"]} instead of {", ".join(beat["claims"])}'
    return None, 'every claim shares a key word with every fact sentence'


def planted_slide(lesson, sources):
    slide_file = next((name for name, text in sources.items() if vc.has(text, vc.norm(SLIDE5))), None)
    if slide_file is None:
        return None, 'the sources hold no planted slide error (osmosis sources only)'
    right = next((c for c in claims_of(lesson) if 'hypertonic' in vc.norm(c.get('quote', '') + ' ' + c.get('text', ''))
                  and not vc.has(vc.norm(c.get('quote', '')), vc.norm(SLIDE5)) and c.get('status') != 'conflict'), None)
    if right is None:
        return None, 'no claim states what happens in a hypertonic solution'
    d = copy.deepcopy(lesson)
    rid = right['id']
    flags = {c['id'] for c in claims_of(d) if c.get('other') == rid or (c.get('status') == 'conflict' and vc.has(vc.norm(c.get('quote', '')), vc.norm(SLIDE5)))}
    d['claims'] = [c for c in d['claims'] if not (isinstance(c, dict) and c.get('id') in flags)]
    c = next(x for x in claims_of(d) if x['id'] == rid)
    c.update({'quote': SLIDE5, 'text': SLIDE5, 'file': slide_file, 'source': slide_file, 'where': 'Slide 5'})
    for key in ('status', 'other', 'note', 'notConflict'):
        c.pop(key, None)

    def strip(refs):
        return [x for x in refs if x not in flags] if isinstance(refs, list) else refs
    for scene in d['scenes']:
        keep = []
        for beat in scene['beats']:
            if 'pause' in beat and isinstance(beat['pause'], dict):
                beat['pause']['claims'] = strip(beat['pause'].get('claims')) or [rid]
            elif beat.get('claims'):
                if flags & set(beat['claims']):
                    continue  # the beat that flagged the conflict goes
                if beat['claims'] == [rid]:
                    beat['say'] = SLIDE5
            keep.append(beat)
        scene['beats'] = keep
    for block in ('practice', 'misconception'):
        if isinstance(d.get(block), dict):
            d[block]['claims'] = strip(d[block].get('claims'))
    return [d], f'claim {rid} now quotes slide 5 ({slide_file}); {", ".join(sorted(flags)) or "no"} conflict flag removed'


def self_badge(lesson, sources):
    a = copy.deepcopy(lesson)
    a['verification'] = {'by': 'video_check.py', 'level': 'checked', 'label': 'Checked', 'sha256': '0' * 64}
    b = copy.deepcopy(lesson)
    b.setdefault('learner', {})['checked'] = 'yes'
    return [a, b], 'a hand-written "verification" block; separately learner.checked = "yes"'


TIME = re.compile(r'(?<!\d)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?!\d)')


def _clock(seconds):
    h, rest = divmod(max(0, seconds), 3600)
    m, s = divmod(rest, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def moved_timestamp(lesson, sources):
    raw = getattr(sources, 'raw', {})
    for c in claims_of(lesson):
        fname, where = c.get('file'), str(c.get('where', ''))
        m = TIME.search(where)
        if not m or fname not in raw or not vc.timed_segments(raw[fname]):
            continue
        t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        d = copy.deepcopy(lesson)
        new = _clock(t + SHIFT)
        next(x for x in claims_of(d) if x['id'] == c['id'])['where'] = where[:m.start()] + new + where[m.end():]
        return [d], f'claim {c["id"]} "where" {m.group(0)} -> {new} in {fname}'
    return None, 'no claim quotes a timed transcript (the unit tests cover the timestamp gate)'


ATTACKS = [
    ('invented quote', invented_quote),
    ('arithmetic slip', arithmetic_slip),
    ('uncited number', uncited_number),
    ('citation on an unrelated sentence', unrelated_citation),
    ('planted slide error presented silently', planted_slide),
    ('self-set "checked" badge', self_badge),
    ('misquoted video timestamp', moved_timestamp),
]


def run_attacks(lesson, sources):
    """Rows of (attack, applied, caught, first error, gate). caught is 'yes', 'no' or 'not applicable'."""
    rows = []
    for name, attack in ATTACKS:
        try:
            variants, applied = attack(lesson, sources)
        except Exception as exc:  # an attack that cannot be built is reported, never hidden
            rows.append((name, f'could not apply: {exc}', 'not applicable', '', ''))
            continue
        if variants is None:
            rows.append((name, applied, 'not applicable', '', ''))
            continue
        firsts, gates, caught = [], [], True
        for v in variants:
            errors = vc.check(v, sources)[0]
            if not errors:
                caught = False
                firsts.append('(no error)')
                continue
            where, problem, _ = errors[0]
            firsts.append(f'{where}: {problem}')
            gates.append(gate_of(problem))
        rows.append((name, applied, 'yes' if caught else 'no', ' / '.join(firsts), ', '.join(dict.fromkeys(gates))))
    return rows


def table(rows):
    def cell(s):
        return str(s).replace('|', '\\|').replace('\n', ' ')
    out = ['| # | Attack | Applied to | Caught | First error | Gate |', '| --- | --- | --- | --- | --- | --- |']
    for i, (name, applied, caught, first, gate) in enumerate(rows, 1):
        out.append(f'| {i} | {cell(name)} | {cell(applied)} | {caught} | {cell(first[:220])} | {cell(gate)} |')
    return '\n'.join(out)


# ---------------------------------------------------------------- the built-in lesson

TRANSCRIPT = """[0:00] Welcome back to Biology 101. Today we finish osmosis and tonicity.
[0:12] Last time we said water crosses the membrane by osmosis.
[0:25] Today the question is what happens to a red blood cell in different solutions.
[0:38] Keep three beakers in mind, because the exam diagram uses three beakers.
[0:51] First, a quick word on how we measure the solution.
[1:04] We write the salt as grams per one hundred milliliters of water.
[1:17] So a one percent solution has one gram in every one hundred milliliters.
[1:30] Hospitals use a solution called normal saline in IV bags.
[1:43] Normal saline is 0.9 percent salt, and it is isotonic to red blood cells.
[1:56] That is why a red blood cell keeps its shape in normal saline.
[2:09] If the salt outside is higher than that, the solution is hypertonic.
[2:22] In a hypertonic solution the red blood cell loses water and shrivels.
[2:35] If the salt outside is lower, the solution is hypotonic and water rushes in.
[2:48] On the exam you will name each beaker from the shape of the cell.
[3:01] That is all for today. Read the next section before Thursday.
"""


def _claim(cid, text, file, where, quote, **extra):
    return {'id': cid, 'text': text, 'from': 'course', 'where': where, 'source': file, 'file': file, 'quote': quote, **extra}


def builtin_lesson():
    return {
        'format': 'myelinate-video/1', 'title': 'Osmosis and the three beakers', 'lessonType': 'concept', 'wpm': 145,
        'learner': {'kind': 'course', 'course': 'BIO 101', 'materials': ['slides', 'notes', 'lecture video']},
        'objectives': ['Explain which way water moves in each solution'],
        'question': 'Which way does water move in each beaker?',
        'calc': [{'id': 'k1', 'expr': '500 * 0.9 / 100', 'value': 4.5},
                 {'id': 'k2', 'expr': 'k1 * 4', 'value': 18}],
        'claims': [
            _claim('c1', 'Osmosis is the diffusion of water across a selectively permeable membrane.', 'bio101-slides.md', 'Slide 1',
                   'Osmosis is the diffusion of water across a selectively permeable membrane.'),
            _claim('c2', 'In a hypertonic solution water leaves the cell and it shrinks.', 'my-notes.md', 'Notes, Sept 18, line 1',
                   'Hypertonic = more solute OUTSIDE the cell. Water leaves the cell and it shrinks.'),
            _claim('c3', 'Slide 5 says a cell in a hypertonic solution gains water and swells.', 'bio101-slides.md', 'Slide 5', SLIDE5,
                   status='conflict', other='c2',
                   note='Slide 5 says the cell swells; the notes and the lecture say it loses water. Ask the professor which the exam uses.'),
            _claim('c5', 'Normal saline is 0.9 percent salt and isotonic to red blood cells.', 'lecture-transcript.txt', 'Lecture video, 1:43',
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
                {'pause': {'ask': 'How many grams of salt are in two liters of normal saline?', 'answer': '18 grams',
                           'why': 'Two liters is four bags of five hundred milliliters, each with four point five grams.', 'claims': ['k1', 'k2']}}]},
        ],
        'recall': {'ask': 'Look away and name what happens in each beaker.',
                   'points': ['Hypertonic: water leaves, the cell shrinks.', 'Hypotonic: water enters.']},
        'practice': {'ask': 'A cell sits in a beaker with more solute outside. Which way does water move?',
                     'answer': 'Out of the cell, so it shrinks.', 'claims': ['c2']},
    }


def attack_file(lesson, source_paths, out=None):
    sources = vc.load_sources(source_paths)
    if not sources:
        print('NO SOURCES: --sources named no readable .txt, .md, .html, .csv, .json, .vtt or .srt file.')
        return 2
    errors = vc.check(lesson, sources)[0]
    if errors:
        where, problem, _ = errors[0]
        print(f'NOT ATTACKED: the checker does not pass this lesson with these sources ({len(errors)} error(s)).')
        print(f'First error: {where} {problem}')
        print('Fix the lesson until scripts/video_check.py prints READY with the same --sources, then attack it.')
        return 2
    rows = run_attacks(lesson, sources)
    text = table(rows)
    print(text)
    applicable = [r for r in rows if r[2] != 'not applicable']
    missed = [r for r in applicable if r[2] != 'yes']
    print(f'\n{len(applicable) - len(missed)} of {len(applicable)} applicable attacks caught; {len(rows) - len(applicable)} not applicable.')
    if out:
        Path(out).write_text(text + '\n')
        print(f'Wrote {out}.')
    return 1 if missed else 0


def self_test(out=None):
    work = Path(tempfile.mkdtemp(prefix='video-attacks-'))
    transcript = work / 'lecture-transcript.txt'
    transcript.write_text(TRANSCRIPT)
    sources = vc.load_sources([OSMOSIS, transcript])
    lesson = builtin_lesson()
    errors = vc.check(lesson, sources)[0]
    if errors:
        print('SELF-TEST BROKEN: the built-in lesson does not pass the checker:')
        for where, problem, _ in errors:
            print(f'- {where} {problem}')
        return 1
    rows = run_attacks(lesson, sources)
    text = table(rows)
    print(text)
    if out:
        Path(out).write_text(text + '\n')
    caught = sum(1 for r in rows if r[2] == 'yes')
    if caught != len(ATTACKS):
        print(f'\nSELF-TEST FAILED: {caught} of {len(ATTACKS)} attacks caught. Every attack must apply and be caught.')
        return 1
    print(f'\nSELF-TEST PASSED: {caught} of {len(ATTACKS)} attacks caught by the checker.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lesson', nargs='?')
    ap.add_argument('--sources', action='append', help='the source files as text, a file or a folder (repeatable)')
    ap.add_argument('--out', help='also write the table to this Markdown file')
    ap.add_argument('--self-test', action='store_true', help='attack the built-in osmosis lesson; exit 1 unless all seven are caught')
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test(a.out)
    if not a.lesson or not a.sources:
        ap.error('give a lesson file and --sources, or --self-test')
    lesson, note = vc.read_lesson(a.lesson)
    if note:
        print('NOTE: ' + note)
    return attack_file(lesson, a.sources, a.out)


if __name__ == '__main__':
    sys.exit(main())
