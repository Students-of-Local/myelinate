"""Blind head-to-head: Myelinate against the best learning plugins, each on its home turf.

usage: python3 evals/head-to-head/rivals.py OUTDIR MYELINATE_ROOT RIVALS_JSON [--scenarios FILE] [--repeats N] [--only id,id] [--arms a,b] [--jobs N]

RIVALS_JSON maps a rival name to the local folder or file it was unpacked to. Rival texts
are other people's work under their own licenses, so none of them is vendored here.
Responder: Sonnet through `claude -p` with no tools. Judge: Opus, blind, order randomized.
Results: one JSON per pair in OUTDIR, and OUTDIR/summary.json with the means and wins.
"""
import concurrent.futures as cf
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
BASE = ["claude", "-p", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence"]
ENV_DEFAULT = "No tools are available this turn. If a visual would help, draw it with markdown, ASCII or a code block."


def opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def rival_text(name, scen, rivals):
    """The text that rival would really load for this scenario."""
    root = Path(rivals[name])
    pick = scen.get("rival_files", {}).get(name)
    if pick:
        return "\n\n".join((root / p).read_text() for p in pick)
    if root.is_file():
        return root.read_text()
    sys.exit(f"rival {name!r} is a folder and scenario {scen['id']!r} names no rival_files for it; refusing to compare against an empty skill")


def myelinate_text(scen, root):
    parts = [(root / "myelinate.md").read_text()]
    for s in scen.get("subs", []):
        parts.append(f"\n\n# Loaded sub-skill file skills/{s}/SKILL.md\n\n" + (root / f"skills/{s}/SKILL.md").read_text())
    return "".join(parts)


def call(model, system, prompt):
    for _ in range(3):
        r = subprocess.run(BASE + ["--model", model, "--system-prompt", system, prompt],
                           capture_output=True, text=True, timeout=900, cwd=HERE)
        if r.stdout.strip():
            return r.stdout.strip()
    raise RuntimeError("empty reply: " + r.stderr[:200])


def respond(arm, scen, root, rivals):
    if arm == "vanilla":
        system = "You are Claude, chatting with a person on claude.ai.\n\n" + scen.get("env", ENV_DEFAULT)
    else:
        text = myelinate_text(scen, root) if arm == "myelinate" else rival_text(arm, scen, rivals)
        system = ("You are Claude, chatting with a person on claude.ai. This skill is loaded and you follow it:\n\n<skill>\n"
                  + text + "\n</skill>\n\n" + scen.get("env", ENV_DEFAULT))
    ctx = f"[Memory about this person: {scen['memory']}]\n\n" if scen.get("memory") else ""
    if scen.get("transcript"):
        ctx += "Conversation so far:\n" + scen["transcript"] + "\n\nThe person's new message:\n"
    tail = "\n\n(Write only your next reply to the person.)" if scen.get("transcript") else ""
    return call("sonnet", system, ctx + scen["message"] + tail)


JUDGE = """You are an expert tutor-trainer grading two AI tutor replies blind. Grade only the reply text.
Scenario context:
{ctx}
Person's message: {msg}

Rubric for this scenario: {rubric}

General standard: the person should leave more able to do it themselves, and for a skill should leave knowing what to practice next and how they'll know it's working. Diagnose when the need is unclear, teach directly when they have nothing to discover. One focused question plus a scaffold per tutoring turn; short turns; no answer leaks in hints; no false or hollow praise; honest verdicts; direct help for real deadlines and "just lay it out" requests; resource requests just get made; accuracy and safety matter; warm, direct, adult tone, no emoji. Length is not quality.

Reply A:
<<<
{a}
>>>

Reply B:
<<<
{b}
>>>

Return only JSON: {{"score_A": 1-10, "score_B": 1-10, "winner": "A"|"B"|"tie", "reason": "<=40 words"}}"""


def judge(scen, a, b):
    ctx = (scen.get("memory", "") + "\n" + scen.get("transcript", "")).strip() or "(none)"
    out = call("opus", "You grade tutoring replies. Output JSON only.",
               JUDGE.format(ctx=ctx, msg=scen["message"], rubric=scen["rubric"], a=a, b=b))
    return json.loads(out[out.find("{"): out.rfind("}") + 1])


def main():
    outdir, root, rivals = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
    repeats, jobs = int(opt("--repeats", 1)), int(opt("--jobs", 5))
    only = opt("--only").split(",") if opt("--only") else None
    arms = opt("--arms").split(",") if opt("--arms") else None
    outdir.mkdir(parents=True, exist_ok=True)
    scens = [s for s in json.loads((HERE / opt("--scenarios", "rival-scenarios.json")).read_text()) if not only or s["id"] in only]
    pairs = [(s, opp, k) for s in scens for opp in s["against"] if not arms or opp in arms for k in range(repeats)]
    cache = {}

    def reply(arm, s, k):
        key = (arm, s["id"], k)
        if key not in cache:
            cache[key] = cf.Future()
            try:
                cache[key].set_result(respond(arm, s, root, rivals))
            except Exception as e:
                cache[key].set_exception(e)
        return cache[key].result()

    def one(job):
        s, opp, k = job
        path = outdir / f"{s['id']}--{opp}-{k}.json"
        if path.exists():
            return json.loads(path.read_text())
        mine, theirs = reply("myelinate", s, k), reply(opp, s, k)
        first_mine = random.random() < 0.5
        a, b = (mine, theirs) if first_mine else (theirs, mine)
        v = judge(s, a, b)
        sm, st = (v["score_A"], v["score_B"]) if first_mine else (v["score_B"], v["score_A"])
        w = v["winner"]
        winner = "tie" if w == "tie" else ("myelinate" if (w == "A") == first_mine else opp)
        res = {"id": s["id"], "group": s.get("group"), "opponent": opp, "rep": k, "myelinate": sm, "rival": st,
               "winner": winner, "reason": v.get("reason"), "reply_myelinate": mine, "reply_rival": theirs}
        path.write_text(json.dumps(res, indent=1))
        print(f"{s['id']:<24} vs {opp:<16} M={sm} R={st} {winner:<16} {v.get('reason')}", flush=True)
        return res

    with cf.ThreadPoolExecutor(jobs) as ex:
        results = [r for r in ex.map(lambda j: _safe(one, j), pairs) if r]
    summary = {}
    for r in results:
        d = summary.setdefault(r["opponent"], {"pairs": 0, "wins": 0, "losses": 0, "ties": 0, "mean_myelinate": 0, "mean_rival": 0})
        d["pairs"] += 1
        d["wins"] += r["winner"] == "myelinate"
        d["losses"] += r["winner"] == r["opponent"]
        d["ties"] += r["winner"] == "tie"
        d["mean_myelinate"] += r["myelinate"]
        d["mean_rival"] += r["rival"]
    for d in summary.values():
        d["mean_myelinate"] = round(d["mean_myelinate"] / d["pairs"], 2)
        d["mean_rival"] = round(d["mean_rival"] / d["pairs"], 2)
    losses = [{k: r[k] for k in ("id", "opponent", "myelinate", "rival", "reason")} for r in results if r["winner"] == r["opponent"]]
    failed = len(pairs) - len(results)
    complete = failed == 0 and bool(pairs)
    (outdir / "summary.json").write_text(json.dumps(
        {"complete": complete, "requested": len(pairs), "failed": failed, "arms": summary, "losses": losses}, indent=1))
    print(json.dumps(summary, indent=1))
    if not complete:
        sys.exit(f"INCOMPLETE: {failed} of {len(pairs)} comparisons failed; summary.json is partial and marked complete: false")


def _safe(fn, job):
    try:
        return fn(job)
    except Exception as e:
        print("ERROR", job[0]["id"], job[1], str(e)[:200], flush=True)
        return None


if __name__ == "__main__":
    main()
