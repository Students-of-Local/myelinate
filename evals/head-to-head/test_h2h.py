#!/usr/bin/env python3
"""Unit tests for evals/head-to-head/h2h.py (stubs agy calls, no live model calls).

Run: python3 evals/head-to-head/test_h2h.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import h2h  # noqa: E402


def _verdict(winner: str, a: int = 8, b: int = 7, reason: str = "stub") -> str:
    return json.dumps({"winner": winner, "score_a": a, "score_b": b, "reason": reason})


class TestH2H(unittest.TestCase):
    def _run_stub(self, scenarios: list[dict], judges: list[str], old_text: str = "old", new_text: str = "new",
                  reply_map: dict[str, str] | None = None, extra_args: list[str] | None = None):
        tmp = Path(tempfile.mkdtemp(prefix="test-h2h-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        old_f, new_f, scen_f = tmp / "old.md", tmp / "new.md", tmp / "scenarios.json"
        out_d, ledger = tmp / "out", tmp / "LEDGER.md"
        old_f.write_text(old_text, encoding="utf-8")
        new_f.write_text(new_text, encoding="utf-8")
        scen_f.write_text(json.dumps(scenarios), encoding="utf-8")
        prompts_log: list[str] = []
        it = iter(judges)

        def caller(runner, model, system, prompt, json_schema=None):
            if json_schema is not None or "You grade tutoring replies" in system:
                prompts_log.append(prompt)
                return next(it)
            for marker, text in (reply_map or {}).items():
                if marker in system:
                    return text
            return "clean tutoring reply"

        argv = ["--old", str(old_f), "--new", str(new_f), "--scenarios", str(scen_f),
                "--out", str(out_d), "--ledger", str(ledger), "--jobs", "1"] + (extra_args or [])
        rec, row = h2h.run_eval(h2h.parse_args(argv), caller=caller)
        return rec, row, prompts_log, out_d, ledger, old_f, new_f

    def test_case_1_old_wins_both_orders(self):
        rec, *_ = self._run_stub([{"id": "s1", "message": "Explain osmosis.", "rubric": "clear"}],
                                 [_verdict("A", 9, 6), _verdict("B", 6, 9)])
        r = rec["results"][0]
        self.assertEqual((r["old_wins"], r["new_wins"], r["ties"], r["outcome"]), (2, 0, 0, "old"))

    def test_case_2_split_counts_as_tie(self):
        rec, *_ = self._run_stub([{"id": "s1", "message": "Explain osmosis.", "rubric": "clear"}],
                                 [_verdict("A"), _verdict("A")])
        r = rec["results"][0]
        self.assertEqual((r["old_wins"], r["new_wins"], r["outcome"]), (1, 1, "tie"))
        self.assertEqual((rec["totals"]["tie"], rec["verdict_totals"]["first_position_wins"]), (1, 2))

    def test_case_3_tie_in_both_orders(self):
        rec, *_ = self._run_stub([{"id": "s1", "message": "Explain osmosis.", "rubric": "clear"}],
                                 [_verdict("tie", 8, 8), _verdict("tie", 8, 8)])
        r = rec["results"][0]
        self.assertEqual((r["ties"], r["old_wins"], r["new_wins"], r["outcome"]), (2, 0, 0, "tie"))

    def test_case_4_answer_key_in_both_judge_prompts(self):
        key = "Must state Vmax stays constant and apparent Km increases."
        rec, _, prompts, *_ = self._run_stub(
            [{"id": "k1", "message": "Competitive inhibitor?", "rubric": "acc", "key": key},
             {"id": "k2", "message": "Recursion?", "rubric": "diag"}],
            [_verdict("tie")] * 4,
        )
        self.assertEqual(len(prompts), 4)
        self.assertIn(key, prompts[0])
        self.assertIn(key, prompts[1])
        self.assertNotIn(key, prompts[2])
        self.assertEqual(rec["scenario_counts"], {"total": 2, "keyed": 1, "heldout": 0})

    def test_case_5_deterministic_lint_counts(self):
        sample = "Great start\u2014try [Price] next! \U0001F680"
        self.assertEqual(h2h.lint_reply(sample), {"dashes": 1, "emoji": 1, "placeholders": 1, "search_redirects": 0})
        redir = "See https://vertexaisearch.cloud.google.com/grounding-api-redirect/x and [Ok](https://example.com)"
        self.assertEqual(h2h.lint_reply(redir), {"dashes": 0, "emoji": 0, "placeholders": 0, "search_redirects": 1})
        rec, _, prompts, *_ = self._run_stub(
            [{"id": "s1", "message": "Hi", "rubric": "r"}], [_verdict("tie")] * 2,
            old_text="OLD_MARK", new_text="NEW_MARK",
            reply_map={"OLD_MARK": sample, "NEW_MARK": "Plain answer."},
        )
        self.assertEqual(rec["lint_totals"]["old"], {"dashes": 1, "emoji": 1, "placeholders": 1, "search_redirects": 0})
        self.assertEqual(rec["lint_totals"]["new"], {"dashes": 0, "emoji": 0, "placeholders": 0, "search_redirects": 0})
        for jp in prompts:
            self.assertNotIn("lint", jp.lower())

    def test_case_6_heldout_reported_separately(self):
        rec, row, _, _, ledger, *_ = self._run_stub(
            [{"id": "dev1", "message": "Dev", "rubric": "r"},
             {"id": "ho1", "split": "heldout", "message": "HO", "rubric": "r"}],
            [_verdict("A", 9, 6), _verdict("B", 6, 9), _verdict("B", 5, 9), _verdict("A", 9, 5)],
        )
        self.assertEqual(rec["totals"], {"scenarios": 2, "old": 1, "new": 1, "tie": 0, "failed": 0})
        self.assertEqual((rec["heldout_totals"]["scenarios"], rec["heldout_totals"]["new"], rec["heldout_totals"]["old"]), (1, 1, 0))
        self.assertIn("0/1/0 (n=1)", row)
        self.assertEqual(ledger.read_text(encoding="utf-8").count(h2h.DISCLOSURE), 1)
        h2h.append_ledger(ledger, row)
        self.assertEqual(ledger.read_text(encoding="utf-8").count(h2h.DISCLOSURE), 1)

    def test_case_7_freeze_records_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "frozen.md"
            f.write_text("frozen skill v1\n", encoding="utf-8")
            sha = hashlib.sha256(b"frozen skill v1\n").hexdigest()
            rec, _, _, out_d, *_ = self._run_stub(
                [{"id": "s1", "message": "Hi", "rubric": "r"}], [_verdict("tie")] * 2,
                extra_args=["--freeze", str(f)],
            )
            saved = json.loads((out_d / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["frozen"][str(f)], sha)
            self.assertEqual(len(rec["skills"]["old"]["sha256"]), 64)

    def test_case_8_unparseable_judge_failed_and_continues(self):
        rec, *_ = self._run_stub(
            [{"id": "bad", "message": "Q1", "rubric": "r"}, {"id": "good", "message": "Q2", "rubric": "r"}],
            ["not json", _verdict("A"), _verdict("B", 6, 9), _verdict("A", 9, 6)],
        )
        bad_r, good_r = rec["results"]
        self.assertEqual(bad_r["verdicts"][0]["status"], "failed")
        self.assertNotEqual(bad_r["verdicts"][0]["mapped_winner"], "tie")
        self.assertEqual((bad_r["failed"], bad_r["outcome"], good_r["outcome"]), (1, "failed", "new"))
        self.assertEqual((rec["totals"]["failed"], rec["totals"]["new"], rec["totals"]["tie"]), (1, 1, 0))

    def test_case_9_quota_exits_75(self):
        fake = subprocess.CompletedProcess(["agy"], 1, "", "Error 429: You have exceeded your quota.")
        with mock.patch.object(subprocess, "run", return_value=fake):
            with self.assertRaises(h2h.QuotaError):
                h2h.call_agy("gemini-4-neon-medium", "hi")
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                for name, body in (("old.md", "a"), ("new.md", "b"), ("s.json", '[{"id":"1","message":"m","rubric":"r"}]')):
                    (tmp / name).write_text(body, encoding="utf-8")
                with self.assertRaises(SystemExit) as ctx:
                    h2h.main(["--old", str(tmp / "old.md"), "--new", str(tmp / "new.md"),
                              "--scenarios", str(tmp / "s.json"), "--out", str(tmp / "out"),
                              "--ledger", str(tmp / "L.md"), "--jobs", "1"])
                self.assertEqual(ctx.exception.code, 75)

    def test_call_agy_command_shape(self):
        seen = {}
        def fake_run(cmd, **kw):
            seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"response": _verdict("A")}), "")
        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            out = h2h.call_agy("gemini-4-neon-xhigh", "grade", json_schema=h2h.VERDICT_SCHEMA)
        self.assertEqual(h2h.parse_verdict(out)["winner"], "A")
        self.assertEqual(seen["cmd"][:10], ["agy", "--mode", "plan", "--sandbox", "--output-format", "json",
                                            "--model", "gemini-4-neon-xhigh", "--print-timeout", "900s"])
        self.assertIn("--json-schema", seen["cmd"])
        self.assertTrue(seen["cmd"][-1].startswith("-p="))
        self.assertNotEqual(Path(seen["cwd"]).resolve(), Path.cwd().resolve())

    def test_swap_puts_each_reply_under_the_other_letter(self):
        # The second order must swap the replies, not only the labels: old under A first, then under B.
        rec, _, prompts, *_ = self._run_stub([{"id": "s1", "message": "Explain osmosis."}],
                                             [_verdict("A", 9, 6), _verdict("B", 6, 9)], old_text="OLDSKILL",
                                             new_text="NEWSKILL", reply_map={"OLDSKILL": "OLD-REPLY", "NEWSKILL": "NEW-REPLY"})
        a0, b0 = prompts[0].split("Reply B:")
        a1, b1 = prompts[1].split("Reply B:")
        self.assertIn("OLD-REPLY", a0); self.assertIn("NEW-REPLY", b0)
        self.assertIn("NEW-REPLY", a1); self.assertIn("OLD-REPLY", b1)
        v = rec["results"][0]["verdicts"]
        self.assertEqual((v[0]["score_old"], v[0]["score_new"], v[1]["score_old"], v[1]["score_new"]), (9, 6, 9, 6))

    def _stub_args(self, n: int, jobs: int):
        tmp = Path(tempfile.mkdtemp(prefix="test-h2h-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "o.md").write_text("o", encoding="utf-8"); (tmp / "n.md").write_text("n", encoding="utf-8")
        (tmp / "s.json").write_text(json.dumps([{"id": f"s{i}", "message": "m"} for i in range(n)]), encoding="utf-8")
        return h2h.parse_args(["--old", str(tmp / "o.md"), "--new", str(tmp / "n.md"), "--scenarios", str(tmp / "s.json"),
                               "--out", str(tmp / "out"), "--no-ledger", "--jobs", str(jobs)])

    def test_quota_in_one_worker_stops_the_other(self):
        import threading
        calls, lock = [0], threading.Lock()

        def caller(runner, model, system, prompt, json_schema=None):
            with lock:
                calls[0] += 1
                n = calls[0]
            if n == 3:
                raise h2h.QuotaError("429 quota")
            return _verdict("tie", 8, 8) if json_schema is not None or "You grade" in system else "reply"
        with self.assertRaises(h2h.QuotaError):
            h2h.run_eval(self._stub_args(20, 2), caller=caller)
        # 20 scenarios at 4 calls each is 80; after the quota only calls already in flight may finish.
        self.assertLessEqual(calls[0], 5)

    def test_judge_sign_in_failure_stops_the_run(self):
        calls = [0]

        def caller(runner, model, system, prompt, json_schema=None):
            calls[0] += 1
            if json_schema is not None or "You grade" in system:
                raise h2h.FatalError("agy authentication required")
            return "reply"
        with self.assertRaises(h2h.FatalError):
            h2h.run_eval(self._stub_args(5, 1), caller=caller)
        self.assertEqual(calls[0], 3)  # two replies, then the first judge call

    def test_four_judge_failures_in_a_row_stop_the_run(self):
        calls = [0]

        def caller(runner, model, system, prompt, json_schema=None):
            calls[0] += 1
            return "not json" if json_schema is not None or "You grade" in system else "reply"
        with self.assertRaises(h2h.FatalError):
            h2h.run_eval(self._stub_args(10, 1), caller=caller)
        self.assertEqual(calls[0], 8)  # two scenarios: 2 replies and 2 failed verdicts each


if __name__ == "__main__":
    res = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestH2H))
    sys.exit(0 if res.wasSuccessful() else 1)
