#!/usr/bin/env python3
"""Committed results of the small-model make-video run, and the floors they must keep.

usage:
  python3 evals/make-video/results.py RUNDIR --model NAME [--out PATH]   write a result from a run
  python3 evals/make-video/results.py --check [PATH]                    CI: check the committed result
  python3 evals/make-video/results.py --self-test                       CI: the check catches doctored results

RUNDIR is what small_model.py wrote (runs.json) after judge.py added judgments.json. The result keeps
one row per scenario and arm: whether the checker passed it, the problems left in its best draft
(null when no draft was valid JSON, so the player cannot open it), how many of its beats say something
aloud (a lesson with none plays nothing, so it is not playable), how many drafts were valid, and the
blind judge's scores. --check recomputes the summary from the rows and fails when the result is
partial, when its rows and summary disagree, or when the skill arm falls below results/floors.json.

Floors only move up. Lowering one needs a written reason in floors.json "note" and in the pull request.
No model runs here; the run itself is a local step (small_model.py, then judge.py).
"""
import copy, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE / 'results' / 'latest.json'
FLOORS = HERE / 'results' / 'floors.json'
ARMS = ('skill', 'baseline')


def say_beats(path):
    """How many beats in the lesson say something aloud: a draft with none is not a video, however few errors it has."""
    try:
        lesson = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    scenes = lesson.get('scenes') if isinstance(lesson, dict) else None
    return sum(1 for sc in scenes if isinstance(sc, dict) and isinstance(sc.get('beats'), list)
               for b in sc['beats'] if isinstance(b, dict) and str(b.get('say') or '').strip()) if isinstance(scenes, list) else 0



def better_draft(errors, beats, best_errors, best_beats, peak=0):
    """Whether a new valid draft should replace the best one. A READY draft (no errors, something said)
    always wins. Otherwise content first: a draft with under half the most spoken beats any valid draft
    has had ranks below one that keeps them, however few errors it has. Fewest errors alone kept a draft
    with no scenes (33 errors) over one with ten (72) in runs5, and every later round built on the empty
    one; measuring against the peak, not the current best, stops a lesson shrinking a step at a time."""
    p = max(peak, beats, best_beats)

    def rank(e, b):
        return (not (e == 0 and b > 0), b * 2 < p, e, -b)
    return rank(errors, beats) <= rank(best_errors, best_beats)


def next_round(state, errors, beats, draft, report):
    """One round of the harness: keep the draft if it is better, then choose what the next prompt edits.
    state is {"best": (errors, beats, draft, report) or None, "peak": int}. Returns (state, base draft,
    base report, note). The next prompt edits the best draft whenever the last one was not kept, so a
    gutted or broken draft is never built on."""
    best, peak = state['best'], state['peak']
    if errors is not None:
        peak = max(peak, beats)
        if best is None or better_draft(errors, beats, best[0], best[1], peak):
            best = (errors, beats, draft, report)
    state = {'best': best, 'peak': peak}
    if best is None or best[2] == draft:
        return state, draft, report, 'Your last draft of the lesson JSON, and what the checker printed for it.'
    if errors is None:
        why = 'was not valid JSON and the checker could not repair it'
    elif beats * 2 < peak:
        why = f'says only {beats} sentence(s) aloud, under half of the {peak} your fullest draft had: keep every scene and beat'
    else:
        why = f'has {errors} problem(s), more than your best draft\'s {best[0]}'
    return state, best[2], best[3], (f'Your last reply {why}, so it was set aside. '
                                      'Here is your best draft so far, and what the checker printed for it.')


def rows_from(rundir):
    runs = json.loads((rundir / 'runs.json').read_text())
    judged = json.loads((rundir / 'judgments.json').read_text())['pairs']
    pairs = {(p['id'], p['rep']): p for p in judged}
    rows = []
    for r in runs:
        p = pairs.get((r['id'], r['rep']))
        if p is None:
            raise SystemExit(f"{r['id']} rep {r['rep']} has no judgment; run judge.py on {rundir} first")
        s = p['scores'][r['arm']]
        rows.append({'id': r['id'], 'arm': r['arm'], 'rep': r['rep'], 'rounds': len(r['rounds']),
                     'valid_drafts': sum(bool(x.get('valid_json')) for x in r['rounds']),
                     'ready': bool(r['ready']), 'final_errors': r['final_errors'], 'say_beats': beats_of(rundir, r),
                     'won': p['winner'] == r['arm'], 'teaches_false': bool(s.get('teaches_false')),
                     'overall': s['overall'], 'accuracy': s['accuracy']})
    return sorted(rows, key=lambda x: (x['id'], x['arm'], x['rep']))


def beats_of(rundir, r):
    """The best draft's spoken beats: from run.json, or for a run made before it logged them, counted
    from the lesson.json it kept (an invalid best draft has none)."""
    if 'final_beats' in r:
        return r['final_beats']
    if r['final_errors'] is None:
        return 0
    lesson = rundir / f"{r['id']}-{r['arm']}-{r['rep']}" / 'lesson.json'
    if not lesson.is_file():
        raise SystemExit(f'{lesson} is missing, and its run.json has no final_beats; the playable count needs one of them')
    return say_beats(lesson)


def summarize(rows):
    out = {}
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        playable = [r for r in rs if r['final_errors'] is not None and r['say_beats'] > 0]
        out[arm] = {'lessons': len(rs), 'ready': sum(r['ready'] for r in rs), 'playable': len(playable),
                    'problems_left': sum(r['final_errors'] for r in playable),
                    'valid_drafts': sum(r['valid_drafts'] for r in rs), 'drafts': sum(r['rounds'] for r in rs),
                    'wins': sum(r['won'] for r in rs), 'teaches_false': sum(r['teaches_false'] for r in rs),
                    'mean_overall': round(sum(r['overall'] for r in rs) / len(rs), 2) if rs else 0}
    return out


def problems(result, floors):
    """Every reason the result fails, as plain sentences."""
    errs = []
    rows = result.get('rows')
    if not isinstance(rows, list) or not rows:
        return ['the result has no rows']
    for key in ('model', 'rounds'):
        if result.get(key) != floors['protocol'][key]:
            errs.append(f'{key} is {result.get(key)!r}; floors.json requires {floors["protocol"][key]!r}')
    want = {(s, a) for s in floors['scenarios'] for a in ARMS}
    have = {(r['id'], r['arm']) for r in rows}
    if want - have:
        errs.append(f'partial run: no row for {sorted(want - have)}')
    if any(not isinstance(r.get('say_beats'), int) for r in rows):
        errs.append('a row has no "say_beats"; rewrite the result with results.py RUNDIR')
    if errs:
        return errs  # summarize needs every row's count
    if summarize(rows) != result.get('summary'):
        errs.append('the summary does not match the rows; rewrite the result with results.py RUNDIR')
    s, f = summarize(rows)['skill'], floors['skill']
    for key in ('ready', 'playable', 'wins'):
        if s[key] < f['min_' + key]:
            errs.append(f'skill {key} is {s[key]}, below the floor of {f["min_" + key]}')
    for key in ('problems_left', 'teaches_false'):
        if s[key] > f['max_' + key]:
            errs.append(f'skill {key} is {s[key]}, above the ceiling of {f["max_" + key]}')
    return errs


def self_test():
    floors = json.loads(FLOORS.read_text())
    good = json.loads(RESULT.read_text())
    fails = []
    if problems(good, floors):
        fails.append(f'the committed result should pass: {problems(good, floors)}')
    skill = [r for r in good['rows'] if r['arm'] == 'skill']

    def doctored(change):
        bad = copy.deepcopy(good)
        change(bad)
        return bad
    cases = {
        'a row dropped': doctored(lambda b: b['rows'].remove(next(r for r in b['rows'] if r['arm'] == 'skill'))),
        'a summary edited by hand': doctored(lambda b: b['summary']['skill'].update(wins=99)),
        'another model': doctored(lambda b: b.update(model='some-other-model')),
    }
    if skill and any(r['final_errors'] is not None for r in skill):
        def worse(b):
            r = next(r for r in b['rows'] if r['arm'] == 'skill' and r['final_errors'] is not None)
            r['final_errors'] += floors['skill']['max_problems_left'] + 1
            b['summary'] = summarize(b['rows'])
        cases['more problems left'] = doctored(worse)

        def silent(b):  # a valid draft with no scenes is not a video (runs5 kept one as the best draft)
            for r in b['rows']:
                if r['arm'] == 'skill':
                    r['say_beats'] = 0
            b['summary'] = summarize(b['rows'])
        if floors['skill']['min_playable'] > 0:
            cases['lessons that say nothing'] = doctored(silent)
        cases['a row with no beat count'] = doctored(lambda b: b['rows'][0].pop('say_beats'))

    def falsehood(b):
        for r in b['rows']:
            if r['arm'] == 'skill':
                r['teaches_false'] = True
        b['summary'] = summarize(b['rows'])
    if floors['skill']['max_teaches_false'] < len(skill):
        cases['the skill teaching false facts'] = doctored(falsehood)
    for name, bad in cases.items():
        if not problems(bad, floors):
            fails.append(f'{name} was not caught')
    # The harness keeps content. Each case is the (errors, beats) of each round's draft (None: invalid
    # JSON), the draft lesson.json must end on, and the draft each next prompt must edit.
    def play(seq):
        state, bases = {'best': None, 'peak': 0}, []
        for n, (e, b) in enumerate(seq):
            state, base, _, _ = next_round(state, e, b, f'draft{n}', f'report{n}')
            bases.append(base)
        return state['best'][2] if state['best'] else None, bases
    for seq, kept, bases, what in (
            ([(72, 14), (33, 0)], 'draft0', ['draft0', 'draft0'], 'a draft with no scenes replaced a ten-scene one, or the next prompt built on it'),
            ([(72, 14), (33, 1)], 'draft0', ['draft0', 'draft0'], 'a draft cut to one beat replaced a fourteen-beat one'),
            ([(33, 1), (72, 14)], 'draft1', ['draft0', 'draft1'], 'a full draft did not replace a gutted one'),
            ([(20, 14), (10, 12)], 'draft1', ['draft0', 'draft1'], 'a similar draft with fewer errors was not kept'),
            ([(10, 12), (20, 14)], 'draft0', ['draft0', 'draft0'], 'a similar draft with more errors was kept or built on'),
            ([(40, 14), (30, 8), (20, 5), (10, 3)], 'draft1', ['draft0', 'draft1', 'draft1', 'draft1'], 'a lesson shrank a step at a time (14, 8, 5, 3 beats)'),
            ([(20, 14), (0, 6)], 'draft1', ['draft0', 'draft1'], 'a READY draft was not kept'),
            ([(20, 14), (None, 0)], 'draft0', ['draft0', 'draft0'], 'a broken reply was built on')):
        if play(seq) != (kept, bases):
            fails.append(f'{what}: got {play(seq)}')
    for f in fails:
        print('FAIL:', f)
    print(f'SELF-TEST {"FAILED" if fails else "PASSED"}: {len(cases) - sum("not caught" in f for f in fails)} of {len(cases)} doctored results caught.')
    return 1 if fails else 0


def main():
    a = sys.argv[1:]
    if '--self-test' in a:
        return self_test()
    if '--check' in a:
        rest = [x for x in a if x != '--check']
        path = Path(rest[0]) if rest else RESULT
        errs = problems(json.loads(path.read_text()), json.loads(FLOORS.read_text()))
        for e in errs:
            print('FAIL:', e)
        if not errs:
            s = json.loads(path.read_text())['summary']['skill']
            print(f"PASS: small-model result meets the floors (skill: {s['ready']} ready, {s['playable']} of {s['lessons']} playable, "
                  f"{s['problems_left']} problems left, preferred by the blind judge in {s['wins']} of {s['lessons']}, {s['teaches_false']} teaching a false fact).")
        return 1 if errs else 0
    if not a or '--model' not in a:
        print(__doc__)
        return 2
    rundir = Path(a[0])
    model = a[a.index('--model') + 1]
    out = Path(a[a.index('--out') + 1]) if '--out' in a else RESULT
    rows = rows_from(rundir)
    rounds = max(r['rounds'] for r in rows if r['arm'] == 'skill')
    result = {'model': model, 'rounds': rounds, 'run': rundir.name, 'rows': rows, 'summary': summarize(rows)}
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(result['summary'], indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
