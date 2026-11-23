#!/usr/bin/env python3
"""Blind judge for the small-model make-video run.

usage: python3 evals/make-video/judge.py RUNDIR [--out results.json] [--no-frames]

For each scenario and repeat, the skill lesson and the baseline lesson are built into the
player, four frames of each are rendered (when a browser driver exists: Python Playwright,
or Node with playwright-core), and Opus grades the pair blind, in random order, against the
scenario's rubric and the learner's own materials. A lesson that is not valid JSON cannot
play, and the judge is told so.

Writes RUNDIR/judgments.json and prints a summary per arm. Judge: Opus via `claude -p`
(the Claude sign-in, no API key).
"""
import json, random, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import video_check  # noqa: E402

CLAUDE = ['claude', '-p', '--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
          '--no-session-persistence', '--model', 'opus', '--tools', 'Read', '--allowedTools', 'Read']

NODE_SHOTS = r"""
const [file, outdir] = process.argv.slice(1);
let pw; try { pw = require('playwright'); } catch (e) { pw = require('playwright-core'); }
(async () => {
  const b = await pw.chromium.launch();
  const p = await b.newPage({viewport: {width: 1280, height: 720}});
  await p.goto('file://' + file + '?export=1');
  await p.waitForFunction(() => window.__video && window.__video.duration > 0, null, {timeout: 15000});
  const times = await p.evaluate(() => {
    const tl = __video.timeline(), d = __video.duration, ts = [];
    const pause = tl.find(i => i.kind === 'pause');
    [0.12, 0.4, 0.7].forEach(f => ts.push(d * f));
    if (pause) ts.push(pause.start + 1); else ts.push(d * 0.9);
    return ts.sort((a, b) => a - b);
  });
  for (let i = 0; i < times.length; i++) {
    await p.evaluate(t => __video.renderAt(t), times[i]);
    await p.waitForTimeout(80);
    await p.screenshot({path: outdir + '/frame' + (i + 1) + '.png'});
  }
  await b.close();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def frames(html, outdir):
    """Render four frames of a built lesson; return their paths, or [] when no driver exists."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        have_py = True
    except ImportError:
        have_py = False
    if have_py:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page(viewport={'width': 1280, 'height': 720})
            p.goto(html.as_uri() + '?export=1')
            p.wait_for_function('window.__video && window.__video.duration > 0', timeout=15000)
            d = p.evaluate('__video.duration')
            pause = p.evaluate("(__video.timeline().find(i => i.kind === 'pause') || {}).start")
            times = sorted([d * 0.12, d * 0.4, d * 0.7, (pause + 1) if pause is not None else d * 0.9])
            out = []
            for i, t in enumerate(times, 1):
                p.evaluate('t => __video.renderAt(t)', t)
                p.wait_for_timeout(80)
                path = outdir / f'frame{i}.png'
                p.screenshot(path=str(path))
                out.append(path)
            b.close()
            return out
    if shutil.which('node'):
        r = subprocess.run(['node', '-e', NODE_SHOTS, str(html), str(outdir)], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return sorted(outdir.glob('frame*.png'))
        print('frames failed:', r.stderr.strip()[:200])
    return []


def prepare(rundir, want_frames):
    """Build each lesson and render its frames. Returns {name: {valid, lesson_text, report, frames}}."""
    info = {}
    for d in sorted(p for p in rundir.iterdir() if p.is_dir() and (p / 'lesson.json').exists()):
        text = (d / 'lesson.json').read_text()
        rounds = sorted(d.glob('report*.txt'), key=lambda p: int(re.sub(r'\D', '', p.stem)))
        report = rounds[-1].read_text() if rounds else ''
        entry = {'valid': True, 'lesson_text': text, 'report': report, 'frames': []}
        try:
            lesson = json.loads(text)
        except json.JSONDecodeError:
            entry['valid'] = False
            info[d.name] = entry
            continue
        if want_frames:
            html = d / 'video.html'
            html.write_text(video_check.embed(lesson))
            entry['frames'] = [str(p) for p in frames(html, d)]
        info[d.name] = entry
    return info


JUDGE = """You are grading two teaching-video lessons made by a small language model for the same learner.
Each lesson is a JSON file that a fixed video player narrates and animates. Judge the lesson as the learner would
experience it, and judge its facts against the learner's materials below. You do not know which method made which.

The learner's request:
<<<
{message}
>>>

The learner's materials (the only sources):
<<<
{materials}
>>>

What a strong lesson does here: {rubric}

{blocks}

Score each lesson 1 to 10 on:
- accuracy: every fact matches the materials; nothing invented; errors in the materials are not taught as fact. A lesson that teaches a false fact scores 3 or lower.
- pedagogy: clear objectives, names before process, an example (worked then faded for problems), a misconception tackled, questions during the video that make the learner think, recall and practice at the end.
- clarity: short plain sentences a learner can follow by ear; screen text that supports rather than repeats the voice.
- visual: from the frames (open each PNG path with the Read tool). A lesson with no frames because it cannot play scores 1.
- overall: how much this lesson would help this learner, all things considered. A lesson that cannot play at all scores at most 2.

Also say, for each, whether it teaches any false statement as fact (true or false), and name it.

Return only JSON:
{{"A": {{"accuracy": n, "pedagogy": n, "clarity": n, "visual": n, "overall": n, "teaches_false": true|false, "false_fact": "..."}},
  "B": {{...same keys...}}, "winner": "A"|"B"|"tie", "reason": "40 words or fewer"}}"""


def block(label, e):
    if not e['valid']:
        return f'LESSON {label}: the model did not produce valid JSON, so the player cannot open it. Its raw output starts:\n<<<\n{e["lesson_text"][:1500]}\n>>>'
    frames = '\n'.join(e['frames']) or '(no frames rendered)'
    return (f'LESSON {label}:\n<<<\n{e["lesson_text"][:14000]}\n>>>\nIts frames (Read these PNG files):\n{frames}')


def judge_pair(scen, a, b, materials, rundir):
    prompt = JUDGE.format(message=scen['message'], materials=materials, rubric=scen['rubric'],
                          blocks=block('A', a) + '\n\n' + block('B', b))
    for _ in range(2):
        # The prompt goes on stdin: --add-dir takes several values and would swallow a prompt argument.
        r = subprocess.run(CLAUDE + ['--add-dir', str(rundir.resolve())], input=prompt, capture_output=True, text=True, timeout=900, cwd=HERE)
        out = r.stdout
        try:
            return json.loads(out[out.find('{'): out.rfind('}') + 1])
        except json.JSONDecodeError:
            continue
    raise RuntimeError('judge output was not JSON: ' + r.stdout[-300:] + r.stderr[-300:])


def materials(scen):
    return '\n'.join(f'--- file: {f.name} ---\n{f.read_text().strip()}\n' for f in sorted((HERE / scen['sources']).iterdir()))


def main():
    rundir = Path(sys.argv[1])
    out = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else rundir / 'judgments.json'
    info = prepare(rundir, '--no-frames' not in sys.argv)
    runs = {f"{r['id']}-{r['arm']}-{r['rep']}": r for r in json.loads((rundir / 'runs.json').read_text())}
    scens = {s['id']: s for s in json.loads((HERE / 'scenarios.json').read_text())}
    results = []
    for name in sorted(n for n in info if '-skill-' in n):
        sid, rep = name.rsplit('-skill-', 1)
        other = f'{sid}-baseline-{rep}'
        if other not in info:
            continue
        order = ['skill', 'baseline']
        random.shuffle(order)
        pair = {'A': f'{sid}-{order[0]}-{rep}', 'B': f'{sid}-{order[1]}-{rep}'}
        v = judge_pair(scens[sid], info[pair['A']], info[pair['B']], materials(scens[sid]), rundir)
        arm = {'A': order[0], 'B': order[1]}
        res = {'id': sid, 'rep': int(rep), 'winner': arm.get(v.get('winner'), 'tie'), 'reason': v.get('reason', ''),
               'scores': {arm[k]: v[k] for k in ('A', 'B')},
               'checker': {a: {'ready': runs[f'{sid}-{a}-{rep}']['ready'], 'final_errors': runs[f'{sid}-{a}-{rep}']['final_errors'],
                               'rounds': len(runs[f'{sid}-{a}-{rep}']['rounds']), 'valid_json': info[f'{sid}-{a}-{rep}']['valid']}
                           for a in ('skill', 'baseline')}}
        results.append(res)
        print(f"{sid} rep {rep}: winner {res['winner']} | skill {res['scores']['skill']['overall']} vs baseline {res['scores']['baseline']['overall']} | {res['reason']}", flush=True)
    summary = {}
    for a in ('skill', 'baseline'):
        n = len(results)
        summary[a] = {
            'pairs': n,
            'wins': sum(r['winner'] == a for r in results),
            'ready': sum(r['checker'][a]['ready'] for r in results),
            'valid_json': sum(r['checker'][a]['valid_json'] for r in results),
            'teaches_false': sum(bool(r['scores'][a].get('teaches_false')) for r in results),
            'mean': {k: round(sum(r['scores'][a][k] for r in results) / n, 2) for k in ('accuracy', 'pedagogy', 'clarity', 'visual', 'overall')} if n else {},
        }
    summary['ties'] = sum(r['winner'] == 'tie' for r in results)
    out.write_text(json.dumps({'summary': summary, 'pairs': results}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
