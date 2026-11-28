#!/usr/bin/env python3
"""Blind head-to-head skill eval on Gemini 4 Neon with two-order judging.

Usage:
  python3 evals/head-to-head/h2h.py --old OLD --new NEW --out OUTDIR [options]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCENARIOS, DEFAULT_LEDGER = HERE / "scenarios.json", HERE / "LEDGER.md"
DEFAULT_RESPONDER, DEFAULT_JUDGE = "gemini-4-neon-medium", "gemini-4-neon-xhigh"
QUOTA_EXIT_CODE = 75
DISCLOSURE = (
    "Neon judges Neon here, so a style preference for its own answers is possible. "
    "Lint counts and answer keys are the check on it."
)
NORMALIZATIONS = [
    "Both orders judged per scenario: (old, new) as (A, B), then (new, old) as (A, B).",
    "A 1-1 split across the two orders counts as a scenario tie.",
    "Responder and judge calls run in an empty temp cwd.",
    "Deterministic lint runs before judging and is excluded from the judge prompt.",
    "Unparseable judge output is recorded as failed, never as a tie.",
]
ENV_DEFAULT = "No tools are available this turn. If a visual would help, draw it with markdown, ASCII or a code block."
CLAUDE_BASE = [
    "claude", "-p", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
    "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
]
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "score_a": {"type": "integer", "minimum": 1, "maximum": 10},
        "score_b": {"type": "integer", "minimum": 1, "maximum": 10},
        "reason": {"type": "string"},
    },
    "required": ["winner", "score_a", "score_b", "reason"],
    "additionalProperties": False,
}
QUOTA_RE = re.compile(
    r"(?i)(quota|rate[\s_-]*limit|too many requests|\b429\b|usage limit|limit reached|"
    r"resource_exhausted|resource exhausted|capacity exhausted|out of (?:extra )?usage|"
    r"credit balance|upgrade your plan|purchase more)"
)
AUTH_RE = re.compile(r"(?i)(authentication required|please sign in|paste the authorization code)")
_EMOJI_BASE = (
    r"(?:[\U0001F1E6-\U0001F1FF]{2}|[\U0001F300-\U0001FAFF\U0001F000-\U0001F02F"
    r"\U0001F0A0-\U0001F0FF\u2600-\u26FF\u2700-\u27BF\u231A-\u231B\u23E9-\u23F3"
    r"\u23F8-\u23FA\u25FD-\u25FE\u2B50\u2B55\u2934-\u2935\u2B05-\u2B07][\uFE0F\U0001F3FB-\U0001F3FF]*)"
)
EMOJI_RE = re.compile(f"{_EMOJI_BASE}(?:\u200D{_EMOJI_BASE})*")
PLACEHOLDER_RE = re.compile(
    r"(?<!\[)\[(?:[A-Z][A-Za-z0-9 _/-]{0,40}|(?:your|insert|enter|add|fill|replace)\s+[A-Za-z0-9 _/-]{1,30})\](?!\s*[\(\[:])"
)
REDIRECT_RE = re.compile(r"(?i)vertexaisearch\.cloud\.google\.com")
LINT_KEYS = ("dashes", "emoji", "placeholders", "search_redirects")

JUDGE_TEMPLATE = """You are an expert tutor-trainer grading two AI tutor replies blind. Grade only the reply text.
Scenario context:
{ctx}
Person's message: {msg}
{rubric_block}{key_block}
General standard: the person should leave more able to do it themselves; diagnose before teaching when the need is unclear;
one focused question plus a scaffold per turn in tutoring; short turns; no answer leaks in hints; no false or hollow praise;
honest verdicts; direct help for real deadlines and for topical "just lay it out" requests; resource requests just get made;
accuracy matters; warm, direct, adult tone, no emoji.

Reply A:
<<<
{a}
>>>

Reply B:
<<<
{b}
>>>

Return only JSON matching: {{"winner": "A"|"B"|"tie", "score_a": 1-10, "score_b": 1-10, "reason": "<=40 words"}}"""


class QuotaError(RuntimeError):
    """Quota or rate-limit hit; caller must stop and exit 75."""


class CallError(RuntimeError):
    """Non-quota model call failure."""


class FatalError(RuntimeError):
    """A failure every later call would repeat (sign-in, missing binary, a judge that keeps failing): stop the run."""


class Stopped(RuntimeError):
    """This worker stopped because another one hit a quota or fatal error; run_eval re-raises that first error."""


JUDGE_FAIL_LIMIT = 4  # judge failures in a row that mean the judge itself is broken, not one bad reply


def hash_skill_path(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    base = path / "myelinate.md" if (path / "myelinate.md").is_file() else path / "SKILL.md"
    if not base.is_file():
        raise FileNotFoundError(f"No myelinate.md or SKILL.md found in {path}")
    h = hashlib.sha256(base.read_bytes())
    if (path / "skills").is_dir():
        for sub in sorted((path / "skills").glob("*/SKILL.md")):
            h.update(b"\n" + str(sub.relative_to(path)).encode() + b"\n" + sub.read_bytes())
    return h.hexdigest()


def load_skill_text(path: Path, scen: dict) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    base = path / "myelinate.md" if (path / "myelinate.md").is_file() else path / "SKILL.md"
    parts = [base.read_text(encoding="utf-8")]
    for sub in scen.get("subs", []):
        p = path / "skills" / sub / "SKILL.md"
        if p.is_file():
            parts.append(f"\n\n# Loaded sub-skill file skills/{sub}/SKILL.md\n\n" + p.read_text(encoding="utf-8"))
    return "".join(parts)


def lint_reply(text: str) -> dict[str, int]:
    return {
        "dashes": text.count("\u2014") + text.count("\u2013"),
        "emoji": len(EMOJI_RE.findall(text)),
        "placeholders": len(PLACEHOLDER_RE.findall(text)),
        "search_redirects": len(REDIRECT_RE.findall(text)),
    }


def is_heldout(scen: dict) -> bool:
    return scen.get("split") in ("heldout", "holdout") or scen.get("group") in ("heldout", "holdout")


def _extract_json(text: str) -> dict:
    s = text.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(s[i:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                continue
    raise ValueError(f"No JSON object found: {s[:160]}")


def call_agy(model: str, prompt: str, json_schema: dict | None = None, timeout: int = 960) -> str:
    cmd = ["agy", "--mode", "plan", "--sandbox", "--output-format", "json", "--model", model, "--print-timeout", "900s"]
    if json_schema is not None:
        cmd.extend(["--json-schema", json.dumps(json_schema)])
    cmd.append(f"-p={prompt}")
    with tempfile.TemporaryDirectory(prefix="h2h-agy-") as tmpdir:
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, cwd=tmpdir)
        except subprocess.TimeoutExpired as exc:
            raise CallError(f"agy timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            raise FatalError("agy not found on PATH") from exc
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    if proc.stderr and QUOTA_RE.search(proc.stderr):
        raise QuotaError(combined[:300])
    if proc.returncode != 0:
        if QUOTA_RE.search(combined):
            raise QuotaError(combined[:300])
        if AUTH_RE.search(combined):
            raise FatalError("agy authentication required; sign in with `agy` first")
        raise CallError(f"agy exited {proc.returncode}: {combined[:240]}")
    if AUTH_RE.search(combined) and not proc.stdout.strip().startswith("{"):
        raise FatalError("agy authentication required; sign in with `agy` first")
    try:
        payload = _extract_json(proc.stdout)
    except ValueError as exc:
        if QUOTA_RE.search(combined):
            raise QuotaError(combined[:300]) from exc
        raise CallError(f"agy returned non-JSON output: {proc.stdout.strip()[:200]}") from exc
    if payload.get("is_error") or payload.get("error"):
        err = json.dumps(payload)
        if QUOTA_RE.search(err):
            raise QuotaError(err[:300])
        if AUTH_RE.search(err):
            raise FatalError("agy authentication required; sign in with `agy` first")
        raise CallError(f"agy error payload: {err[:240]}")
    resp = payload.get("response")
    if resp is None or (isinstance(resp, str) and not resp.strip()):
        if QUOTA_RE.search(combined):
            raise QuotaError(combined[:300])
        raise CallError("agy JSON output missing or empty .response")
    return resp if isinstance(resp, str) else json.dumps(resp)


def call_claude(model: str, system: str, prompt: str, timeout: int = 600) -> str:
    cmd = CLAUDE_BASE + ["--model", model, "--system-prompt", system, prompt]
    with tempfile.TemporaryDirectory(prefix="h2h-claude-") as tmpdir:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, cwd=tmpdir)
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    if (proc.returncode != 0 or not proc.stdout.strip()) and QUOTA_RE.search(combined):
        raise QuotaError(combined[:300])
    if proc.returncode != 0 or not proc.stdout.strip():
        raise CallError(f"claude exited {proc.returncode}: {combined[:240]}")
    return proc.stdout.strip()


def invoke_model(runner: str, model: str, system: str, prompt: str, json_schema: dict | None = None) -> str:
    if runner == "agy":
        return call_agy(model, f"{system}\n\n{prompt}" if system else prompt, json_schema=json_schema)
    if runner == "claude":
        return call_claude(model, system, prompt)
    raise ValueError(f"Unsupported runner: {runner}")


def build_judge_prompt(scen: dict, reply_a: str, reply_b: str) -> str:
    ctx = (scen.get("memory", "") + "\n" + scen.get("transcript", "")).strip() or "(none)"
    rubric_block = f"\nRubric for this scenario: {scen['rubric']}\n" if scen.get("rubric") else ""
    key = scen.get("key")
    key_text = "\n".join(map(str, key)) if isinstance(key, list) else (str(key).strip() if key else "")
    key_block = f"\nAnswer key (grade both replies against these facts and qualities):\n{key_text}\n" if key_text else ""
    return JUDGE_TEMPLATE.format(ctx=ctx, msg=scen["message"], rubric_block=rubric_block, key_block=key_block, a=reply_a, b=reply_b)


def parse_verdict(raw: str) -> dict:
    data = _extract_json(raw)
    w = data.get("winner")
    sa, sb, reason = data.get("score_a", data.get("score_A")), data.get("score_b", data.get("score_B")), data.get("reason")
    if w not in ("A", "B", "tie") or not isinstance(reason, str):
        raise ValueError(f"Invalid verdict fields: {data!r}")
    for k, v in (("score_a", sa), ("score_b", sb)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (1 <= v <= 10):
            raise ValueError(f"Invalid {k}: {v!r}")
    return {"winner": w, "score_a": sa, "score_b": sb, "reason": reason}


def respond(skill_path: Path, scen: dict, runner: str, model: str, caller=invoke_model) -> str:
    system = (
        f"You are an AI tutor chatting with a learner. This skill is loaded and you follow it:\n\n"
        f"<skill>\n{load_skill_text(skill_path, scen)}\n</skill>\n\n" + scen.get("env", ENV_DEFAULT)
    )
    ctx = (f"[Memory about this person: {scen['memory']}]\n\n" if scen.get("memory") else "")
    if scen.get("transcript"):
        ctx += "Conversation so far:\n" + scen["transcript"] + "\n\nThe person's new message:\n"
    tail = "\n\n(Write only your next reply to the person.)" if scen.get("transcript") else ""
    return caller(runner, model, system, ctx + scen["message"] + tail, None)


def judge_both_orders(scen: dict, old_reply: str, new_reply: str, runner: str, judge_model: str, caller=invoke_model,
                      on_judge=None) -> dict:
    orders = [("old", "new", old_reply, new_reply), ("new", "old", new_reply, old_reply)]
    verdicts = []
    for side_a, side_b, reply_a, reply_b in orders:
        try:
            prompt = build_judge_prompt(scen, reply_a, reply_b)
            raw = caller(runner, judge_model, "You grade tutoring replies. Output JSON only.", prompt,
                         VERDICT_SCHEMA if runner == "agy" else None)
            v = parse_verdict(raw)
        except (QuotaError, FatalError, Stopped):
            raise
        except Exception as exc:
            verdicts.append({"order": [side_a, side_b], "status": "failed", "raw_winner": None, "mapped_winner": "failed", "error": str(exc)})
            if on_judge:
                on_judge(False, str(exc))
            continue
        if on_judge:
            on_judge(True, "")
        rw = v["winner"]
        mapped = "tie" if rw == "tie" else (side_a if rw == "A" else side_b)
        verdicts.append({
            "order": [side_a, side_b], "status": "ok", "raw_winner": rw, "mapped_winner": mapped,
            "score_old": v["score_a"] if side_a == "old" else v["score_b"],
            "score_new": v["score_b"] if side_a == "old" else v["score_a"],
            "reason": v["reason"],
        })
    ow = sum(x["mapped_winner"] == "old" for x in verdicts)
    nw = sum(x["mapped_winner"] == "new" for x in verdicts)
    ties = sum(x["mapped_winner"] == "tie" for x in verdicts)
    failed = sum(x["status"] != "ok" for x in verdicts)
    outcome = "failed" if failed else ("old" if ow > nw else ("new" if nw > ow else "tie"))
    return {"verdicts": verdicts, "old_wins": ow, "new_wins": nw, "ties": ties, "failed": failed, "outcome": outcome}


def run_scenario(scen: dict, rep: int, old_p: Path, new_p: Path, runner: str, resp_m: str, judge_m: str, caller=invoke_model,
                 on_judge=None) -> dict:
    old_r, new_r = respond(old_p, scen, runner, resp_m, caller), respond(new_p, scen, runner, resp_m, caller)
    lint = {"old": lint_reply(old_r), "new": lint_reply(new_r)}
    judged = judge_both_orders(scen, old_r, new_r, runner, judge_m, caller, on_judge)
    return {
        "id": scen["id"], "rep": rep, "split": "heldout" if is_heldout(scen) else scen.get("split", "dev"),
        "has_key": bool(scen.get("key")), "replies": {"old": old_r, "new": new_r}, "lint": lint, **judged,
    }


def _tally(items: list[dict]) -> tuple[dict, dict]:
    tot = {"scenarios": len(items), "old": 0, "new": 0, "tie": 0, "failed": 0}
    vt = {"old": 0, "new": 0, "tie": 0, "failed": 0, "first_position_wins": 0, "second_position_wins": 0}
    for r in items:
        tot[r["outcome"]] += 1
        vt["old"] += r["old_wins"]; vt["new"] += r["new_wins"]; vt["tie"] += r["ties"]; vt["failed"] += r["failed"]
        for v in r["verdicts"]:
            if v["status"] == "ok":
                vt["first_position_wins"] += v["raw_winner"] == "A"
                vt["second_position_wins"] += v["raw_winner"] == "B"
    return tot, vt


def format_ledger_row(rec: dict) -> str:
    old, new, sc, tot, ho, m = rec["skills"]["old"], rec["skills"]["new"], rec["scenario_counts"], rec["totals"], rec["heldout_totals"], rec["models"]
    fmt_l = lambda c: f"d={c['dashes']} e={c['emoji']} p={c['placeholders']} r={c['search_redirects']}"
    fp = f" ({tot['failed']} failed)" if tot["failed"] else ""
    hfp = f" ({ho['failed']} failed)" if ho["failed"] else ""
    return (
        f"| {rec['date']} | {old['label']} ({old['sha256'][:12]}) vs {new['label']} ({new['sha256'][:12]}) | "
        f"{sc['total']} ({sc['keyed']} keyed, {sc['heldout']} heldout) | {tot['old']}/{tot['new']}/{tot['tie']}{fp} | "
        f"{ho['old']}/{ho['new']}/{ho['tie']}{hfp} (n={ho['scenarios']}) | "
        f"{fmt_l(rec['lint_totals']['old'])} / {fmt_l(rec['lint_totals']['new'])} | "
        f"resp={m['responder']}, judge={m['judge']} |"
    )


def append_ledger(path: Path, row: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        header = (
            f"# Head-to-head eval ledger\n\n{DISCLOSURE}\n\n"
            "| Date | Skills (sha256) | Scenarios | Old / New / Tie | Held-out | Lint (old / new) | Models |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
        )
        path.write_text(header + row + "\n", encoding="utf-8")
        return
    prev = path.read_text(encoding="utf-8")
    path.write_text(prev + ("" if prev.endswith("\n") else "\n") + row + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blind head-to-head skill eval on Gemini 4 Neon.")
    p.add_argument("--old", required=True, type=Path, help="Old skill file or myelinate repo directory")
    p.add_argument("--new", required=True, type=Path, help="New skill file or myelinate repo directory")
    p.add_argument("--old-label", default=None); p.add_argument("--new-label", default=None)
    p.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    p.add_argument("--out", required=True, type=Path, help="Output directory or .json file")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--no-ledger", action="store_true")
    p.add_argument("--runner", choices=("agy", "claude"), default="agy")
    p.add_argument("--responder-model", default=None); p.add_argument("--judge-model", default=None)
    p.add_argument("--freeze", type=Path, action="append", default=[], help="Skill file to hash and record as frozen")
    p.add_argument("--only", default=None); p.add_argument("--limit", type=int, default=None)
    p.add_argument("--repeats", type=int, default=1); p.add_argument("--jobs", type=int, default=2)
    return p.parse_args(argv)


def run_eval(args: argparse.Namespace, caller=invoke_model) -> tuple[dict, str]:
    resp_m = args.responder_model or (DEFAULT_RESPONDER if args.runner == "agy" else "sonnet")
    judge_m = args.judge_model or (DEFAULT_JUDGE if args.runner == "agy" else "opus")
    scens = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        scens = [s for s in scens if s["id"] in wanted]
    if args.limit is not None:
        scens = scens[:args.limit]
    jobs = [(s, k) for s in scens for k in range(args.repeats)]
    # Hash before any model call: a bad path fails at once, and the record names the text that ran.
    old_sha, new_sha = hash_skill_path(args.old), hash_skill_path(args.new)
    frozen = {str(p): hash_skill_path(p) for p in args.freeze}
    # One stop flag for every worker: after a quota or fatal error no worker makes another model call.
    # The first quota or fatal error is kept and re-raised, so a peer's Stopped never decides the exit code.
    stop = threading.Event()
    lock = threading.Lock()
    fails = [0]
    first: list[BaseException] = []

    def halt(exc: BaseException) -> None:
        with lock:
            if not first:
                first.append(exc)
            stop.set()

    def guarded(*a):
        if stop.is_set():
            raise Stopped("another worker hit a quota limit or a fatal error")
        try:
            return caller(*a)
        except (QuotaError, FatalError) as exc:
            halt(exc)
            raise

    def on_judge(ok: bool, err: str) -> None:
        with lock:
            fails[0] = 0 if ok else fails[0] + 1
            n = fails[0]
        if n >= JUDGE_FAIL_LIMIT:
            exc = FatalError(f"the judge failed {n} times in a row; last error: {err[:200]}")
            halt(exc)
            raise exc

    def one(s, k):
        return run_scenario(s, k, args.old, args.new, args.runner, resp_m, judge_m, guarded, on_judge)

    results: list[dict] = []
    if args.jobs <= 1 or len(jobs) <= 1:
        results = [one(s, k) for s, k in jobs]
    else:
        with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(one, s, k): i for i, (s, k) in enumerate(jobs)}
            done: dict[int, dict] = {}
            try:
                for f in cf.as_completed(futs):
                    done[futs[f]] = f.result()
            except BaseException as exc:
                halt(exc)
                for f in futs:
                    f.cancel()
                raise first[0] from None
            results = [done[i] for i in range(len(jobs))]
    tot, vt = _tally(results)
    ho_items = [r for r in results if r["split"] == "heldout"]
    ho_tot, ho_vt = _tally(ho_items)
    record = {
        "date": dt.date.today().isoformat(), "disclosure": DISCLOSURE, "normalizations": NORMALIZATIONS,
        "runner": args.runner, "models": {"responder": resp_m, "judge": judge_m}, "scenarios_file": str(args.scenarios),
        "skills": {
            "old": {"label": args.old_label or args.old.name, "path": str(args.old), "sha256": old_sha},
            "new": {"label": args.new_label or args.new.name, "path": str(args.new), "sha256": new_sha},
        },
        "frozen": frozen,
        "scenario_counts": {"total": len(results), "keyed": sum(r["has_key"] for r in results), "heldout": len(ho_items)},
        "totals": tot, "verdict_totals": vt, "heldout_totals": {**ho_tot, "verdict_totals": ho_vt},
        "lint_totals": {s: {k: sum(r["lint"][s][k] for r in results) for k in LINT_KEYS} for s in ("old", "new")},
        "results": results,
    }
    out_path = args.out if args.out.suffix == ".json" else args.out / "results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    row = format_ledger_row(record)
    if not args.no_ledger:
        append_ledger(args.ledger, row)
    return record, row


def main(argv: list[str] | None = None, caller=invoke_model) -> int:
    args = parse_args(argv)
    try:
        rec, row = run_eval(args, caller=caller)
    except QuotaError as exc:
        print(f"QUOTA STOP: {exc}", file=sys.stderr)
        sys.exit(QUOTA_EXIT_CODE)
    except FatalError as exc:
        print(f"FATAL STOP: {exc}", file=sys.stderr)
        sys.exit(1)
    print(row)
    t, v = rec["totals"], rec["verdict_totals"]
    print(f"Scenarios: {t['scenarios']} (old={t['old']}, new={t['new']}, tie={t['tie']}, failed={t['failed']}) | "
          f"Verdicts: old={v['old']}, new={v['new']}, tie={v['tie']}, failed={v['failed']} "
          f"(posA={v['first_position_wins']}, posB={v['second_position_wins']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
