#!/usr/bin/env python3
"""Small-model run for make-video: a local model writes lessons with the skill and without it.

usage: python3 evals/make-video/small_model.py OUTDIR [--base-url URL] [--repeats N] [--rounds N] [--only id,id] [--jobs N] [--think]

Arms (same model, same request, same materials):
  skill     SKILL.md and the fill-in template as the system prompt. After each draft the
            checker runs with --sources on the learner's materials and its report goes back
            to the model, up to --rounds drafts in all. This is how the skill tells a model
            with a shell to work. A host with tools edits one file in place; here the model
            rewrites it whole, so a reply that is not JSON even after repair is set aside and
            the next round builds on the best valid draft so far, which lesson.json keeps.
  baseline  No skill. The request asks for the same JSON format (the template) so the
            player can show it. One draft, no checker.

Any OpenAI-compatible server works (llama-server, ollama). Nothing here calls a paid API.
Each run writes OUTDIR/<scenario>-<arm>-<rep>/ with every draft (as the checker left it: it saves
repaired JSON in place), every checker report, lesson.json (the best valid draft) and run.json (errors per
round, valid JSON or not, repaired or not).
Judge the results with judge.py.
"""
import json, re, subprocess, sys, urllib.request, concurrent.futures as cf
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHECK = ROOT / 'scripts' / 'video_check.py'
SKILL = ROOT / 'skills' / 'make-video' / 'SKILL.md'
TEMPLATE = ROOT / 'templates' / 'video-lesson.json'


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


BASE_URL = opt('--base-url', 'http://127.0.0.1:18077/v1')


def materials(scen):
    out = []
    for f in sorted((HERE / scen['sources']).iterdir()):
        out.append(f'--- file: {f.name} ---\n{f.read_text().strip()}\n')
    return '\n'.join(out)


def chat(system, user):
    # Thinking off for both arms: with it on, a 1.7B reasoning model spent its whole budget thinking
    # on this task and wrote no answer (LFM3-1.7B, 2026-11-22). --think turns it back on.
    body = json.dumps({'model': 'local', 'temperature': 0.4, 'max_tokens': 9000,
                       'chat_template_kwargs': {'enable_thinking': '--think' in sys.argv},
                       'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}).encode()
    req = urllib.request.Request(BASE_URL + '/chat/completions', body, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)['choices'][0]['message']['content'] or ''


def extract(reply):
    """The JSON object in a reply: drop thinking, keep the first { to the last }."""
    text = re.sub(r'(?s)<think>.*?</think>', '', reply)
    a, b = text.find('{'), text.rfind('}')
    return text[a:b + 1] if a >= 0 and b > a else text.strip()


def run_check(path, scen):
    r = subprocess.run([sys.executable, str(CHECK), str(path), '--sources', str(HERE / scen['sources'])],
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    m = re.search(r'NOT READY: (\d+) problem', out)
    errors = int(m.group(1)) if m else (0 if r.returncode == 0 else None)  # None: not valid JSON
    return out, errors


def skill_system():
    return ('You are a learning assistant. This skill is loaded and you follow it exactly:\n\n<skill>\n'
            + SKILL.read_text() + '\n</skill>\n\nThe file templates/video-lesson.json:\n```json\n' + TEMPLATE.read_text() + '```\n\n'
            'Today is 2026-11-22. You have no shell and no web access: the person runs scripts/video_check.py for you '
            'and pastes what it prints. Reply with only the lesson JSON, nothing before or after it.')


def run_one(scen, arm, rep, outdir, rounds):
    d = outdir / f"{scen['id']}-{arm}-{rep}"
    d.mkdir(parents=True, exist_ok=True)
    request = scen['message'] + '\n\n' + materials(scen)
    log = {'id': scen['id'], 'arm': arm, 'rep': rep, 'rounds': []}
    if arm == 'skill':
        system, user = skill_system(), request
    else:
        system = 'You are a helpful assistant.'
        user = (request + '\n\nWrite the teaching video as JSON in exactly this format, replacing every <<...>> and adding '
                'scenes as needed. Reply with only the JSON.\n```json\n' + TEMPLATE.read_text() + '```')
        rounds = 1
    best = None  # (errors, draft): the draft the next round builds on, as a file a host would edit in place
    for n in range(1, rounds + 1):
        reply = chat(system, user)
        (d / f'reply{n}.txt').write_text(reply)
        draft = extract(reply)
        (d / f'draft{n}.json').write_text(draft)
        report, errors = run_check(d / f'draft{n}.json', scen)
        (d / f'report{n}.txt').write_text(report)
        draft = (d / f'draft{n}.json').read_text()  # the checker saves a repaired file in place
        log['rounds'].append({'round': n, 'errors': errors, 'valid_json': errors is not None,
                              'repaired': 'Repaired and saved it' in report})
        if errors is not None and (best is None or errors <= best[0]):
            best = (errors, draft, report)
        (d / 'lesson.json').write_text(best[1] if best else draft)
        if errors == 0:
            break
        if best and errors is None:
            note = ('Your last reply was not valid JSON and the checker could not repair it, so it was set aside. '
                    'Here is your best draft so far, and what the checker printed for it.')
            draft, report = best[1], best[2]
        else:
            note = 'Your last draft of the lesson JSON, and what the checker printed for it.'
        user = (request + '\n\n' + note + '\n```json\n' + draft + '\n```\n\n'
                'The checker printed:\n```\n' + report.strip() + '\n```\n\n'
                'Fix every numbered problem exactly as its Fix line says. Change nothing else. '
                'Reply with the whole corrected lesson JSON only.')
    log['ready'] = bool(best) and best[0] == 0
    log['final_errors'] = best[0] if best else None  # the best valid draft, which lesson.json holds
    (d / 'run.json').write_text(json.dumps(log, indent=1))
    print(f"{scen['id']} {arm} {rep}: " + ' -> '.join(str(r['errors']) for r in log['rounds']), flush=True)
    return log


def main():
    outdir = Path(sys.argv[1])
    repeats, rounds, jobs = int(opt('--repeats', 1)), int(opt('--rounds', 4)), int(opt('--jobs', 2))
    only = opt('--only', None)
    scens = [s for s in json.loads((HERE / 'scenarios.json').read_text()) if not only or s['id'] in only.split(',')]
    tasks = [(s, arm, rep) for rep in range(1, repeats + 1) for s in scens for arm in ('skill', 'baseline')]
    with cf.ThreadPoolExecutor(jobs) as ex:
        logs = list(ex.map(lambda t: run_one(*t, outdir, rounds), tasks))
    (outdir / 'runs.json').write_text(json.dumps(logs, indent=1))


if __name__ == '__main__':
    main()
