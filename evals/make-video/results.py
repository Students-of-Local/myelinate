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
                     'ready': bool(r['ready']), 'final_errors': r['final_errors'], 'say_beats': r.get('final_beats', 0),
                     'won': p['winner'] == r['arm'], 'teaches_false': bool(s.get('teaches_false')),
                     'overall': s['overall'], 'accuracy': s['accuracy']})
    return sorted(rows, key=lambda x: (x['id'], x['arm'], x['rep']))


def summarize(rows):
    out = {}
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        playable = [r for r in rs if r['final_errors'] is not None and r.get('say_beats', 0) > 0]
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
