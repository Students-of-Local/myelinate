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


JUDGED = []


def run(fail_ids, tmp=None, scen=SCEN):
    tmp = tmp or Path(tempfile.mkdtemp())
    (tmp / "scen.json").write_text(json.dumps(scen))
    (tmp / "rivals.json").write_text("{}")
    (tmp / "myelinate.md").write_text("router stub")
    rivals.HERE = tmp

    def respond(arm, s, root, rv):
        if s["id"] in fail_ids:
            raise RuntimeError("responder timed out")
        return f"{arm} reply"

    rivals.respond = respond
    def judge(s, a, b):
        JUDGED.append(s["id"])
        return {"score_A": 7, "score_B": 5, "winner": "A", "reason": "stub"}

    rivals.judge = judge
    sys.argv = ["rivals.py", str(tmp / "out"), str(tmp), str(tmp / "rivals.json"), "--scenarios", "scen.json", "--jobs", "1"]
    try:
        rivals.main()
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return code, json.loads((tmp / "out" / "summary.json").read_text()), tmp


failures = []
code, summary, tmp = run(set())
if code != 0 or not summary["complete"] or summary["failed"] != 0:
    failures.append(f"complete run: exit {code}, summary {summary}")
code, summary, tmp = run({"s2"})
if code == 0 or summary["complete"] or summary["failed"] != 1:
    failures.append(f"one failed comparison: exit {code}, summary {summary}")
code, summary, tmp = run({"s1", "s2"})
if code == 0 or summary["complete"]:
    failures.append(f"every comparison failed: exit {code}, summary {summary}")
JUDGED.clear()
code, summary, tmp = run(set())
run(set(), tmp)
if JUDGED != ["s1", "s2"]:
    failures.append(f"unchanged rerun should reuse saved pairs, judged {JUDGED}")
JUDGED.clear()
run(set(), tmp, [dict(SCEN[0], rubric="a new rubric"), SCEN[1]])
if JUDGED != ["s1"]:
    failures.append(f"a changed rubric should rerun only that pair, judged {JUDGED}")
if failures:
    sys.exit("FAIL: " + "; ".join(failures))
print("PASS: rivals.py exits nonzero on an incomplete run and reruns a saved pair whose inputs changed")
