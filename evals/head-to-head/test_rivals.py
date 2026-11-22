#!/usr/bin/env python3
"""rivals.py must refuse to report an incomplete run as a result.

Stubs the responder and judge, so it needs no model. Run: python3 evals/head-to-head/test_rivals.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rivals  # noqa: E402

SCEN = [{"id": "s1", "against": ["vanilla"], "prompt": "p", "rubric": "r"},
        {"id": "s2", "against": ["vanilla"], "prompt": "p", "rubric": "r"}]


def run(fail_ids):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "scen.json").write_text(json.dumps(SCEN))
    (tmp / "rivals.json").write_text("{}")
    rivals.HERE = tmp

    def respond(arm, s, root, rv):
        if s["id"] in fail_ids:
            raise RuntimeError("responder timed out")
        return f"{arm} reply"

    rivals.respond = respond
    rivals.judge = lambda s, a, b: {"score_A": 7, "score_B": 5, "winner": "A", "reason": "stub"}
    sys.argv = ["rivals.py", str(tmp / "out"), str(tmp), str(tmp / "rivals.json"), "--scenarios", "scen.json", "--jobs", "1"]
    try:
        rivals.main()
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return code, json.loads((tmp / "out" / "summary.json").read_text())


failures = []
code, summary = run(set())
if code != 0 or not summary["complete"] or summary["failed"] != 0:
    failures.append(f"complete run: exit {code}, summary {summary}")
code, summary = run({"s2"})
if code == 0 or summary["complete"] or summary["failed"] != 1:
    failures.append(f"one failed comparison: exit {code}, summary {summary}")
code, summary = run({"s1", "s2"})
if code == 0 or summary["complete"]:
    failures.append(f"every comparison failed: exit {code}, summary {summary}")
if failures:
    sys.exit("FAIL: " + "; ".join(failures))
print("PASS: rivals.py exits nonzero and marks summary.json incomplete when any comparison fails")
