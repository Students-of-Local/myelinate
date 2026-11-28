#!/usr/bin/env python3
"""Deterministic unit tests for scripts/fsrs.py (FSRS-lite DSR + Myelinate invariants)."""
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import fsrs  # noqa: E402


def test_forgetting_curve_and_inverse():
    # At t = S, FSRS-4 power curve gives R(S, S) = (1 + 1/9)^-1 = 0.9 exactly.
    r = fsrs.retrievability(10.0, 10.0)
    assert abs(r - 0.9) < 1e-9, f'expected 0.9, got {r}'
    ivl = fsrs.optimal_interval(0.9, 10.0)
    assert abs(ivl - 10.0) < 1e-9, f'expected 10.0, got {ivl}'
    assert fsrs.retrievability(0.0, 5.0) == 1.0
    assert fsrs.retrievability(20.0, 5.0) < fsrs.retrievability(5.0, 5.0)


def test_monotonic_unassisted_recall():
    d0 = date(2026, 11, 1)
    r1 = fsrs.review(None, 'unassisted-correct', elapsed_days=0, today=d0)
    s1 = fsrs.DSRState(**r1['fsrs'])
    assert s1.reps == 1 and s1.lapses == 0 and r1['interval_days'] >= 1
    r2 = fsrs.review(s1, 'unassisted-correct', elapsed_days=r1['interval_days'], today=d0)
    s2 = fsrs.DSRState(**r2['fsrs'])
    assert s2.stability > s1.stability, 'stability must increase on unassisted recall'
    assert r2['interval_days'] > r1['interval_days'], 'interval must grow monotonically on Good'
    r3 = fsrs.review(s2, 'unassisted-easy', elapsed_days=r2['interval_days'], today=d0)
    assert r3['fsrs']['stability'] > s2.stability
    assert r3['interval_days'] > r2['interval_days']
    assert 1.0 <= r3['fsrs']['difficulty'] <= 10.0


def test_hinted_and_self_assessed_never_advance():
    base = fsrs.DSRState(difficulty=5.2, stability=6.0, reps=2, lapses=0, interval_days=6)
    d0 = date(2026, 11, 1)
    for outcome in ('hinted-correct', 'self-assessed'):
        res = fsrs.review(base, outcome, elapsed_days=6.0, today=d0)
        assert res['fsrs']['stability'] == base.stability, f'{outcome} must not raise stability'
        assert res['interval_days'] == base.interval_days, f'{outcome} must not advance interval'
        assert res['fsrs']['reps'] == base.reps


def test_lapse_and_revealed_reset():
    base = fsrs.DSRState(difficulty=4.5, stability=14.0, reps=4, lapses=0, interval_days=14)
    d0 = date(2026, 11, 1)
    for outcome in ('incorrect', 'revealed'):
        res = fsrs.review(base, outcome, elapsed_days=14.0, today=d0)
        assert res['interval_days'] == 1, f'{outcome} must reset interval to 1 day'
        assert res['fsrs']['stability'] < base.stability, f'{outcome} must reduce stability'
        assert res['fsrs']['lapses'] == 1
        assert res['next_review'] == '2026-11-02'


def test_exam_horizon_clamping():
    base = fsrs.DSRState(difficulty=3.5, stability=20.0, reps=4, lapses=0, interval_days=14)
    d0 = date(2026, 11, 1)
    res_7d = fsrs.review(base, 'unassisted-correct', elapsed_days=10.0, days_to_exam=7, today=d0)
    assert 1 <= res_7d['interval_days'] <= 3, f'7-day exam horizon must clamp <= 3d, got {res_7d["interval_days"]}'
    res_2d = fsrs.review(base, 'unassisted-correct', elapsed_days=1.0, days_to_exam=2, today=d0)
    assert res_2d['interval_days'] == 1


def test_study_plan_validation():
    good = {
        'available_hours': 6.0,
        'sleep_hours_per_night': 8.0,
        'days_to_exam': 4,
        'has_drop_list': True,
        'blocks': [
            {'day_offset': 1, 'minutes': 45, 'activity_kind': 'retrieval'},
            {'day_offset': 2, 'minutes': 45, 'activity_kind': 'mixed-practice'},
            {'day_offset': 3, 'minutes': 45, 'activity_kind': 'mock-exam'},
        ],
    }
    assert fsrs.validate_study_plan(good) == []

    bad = {
        'available_hours': 2.0,
        'sleep_hours_per_night': 5.0,
        'days_to_exam': 2,
        'has_drop_list': False,
        'blocks': [
            {'day_offset': 1, 'minutes': 90, 'activity_kind': 'passive-reread'},
            {'day_offset': 3, 'minutes': 60, 'activity_kind': 'retrieval'},
        ],
    }
    errs = fsrs.validate_study_plan(bad)
    assert len(errs) >= 4, f'expected >=4 errors, got {errs}'


def main() -> int:
    for fn in (
        test_forgetting_curve_and_inverse,
        test_monotonic_unassisted_recall,
        test_hinted_and_self_assessed_never_advance,
        test_lapse_and_revealed_reset,
        test_exam_horizon_clamping,
        test_study_plan_validation,
    ):
        fn()
    print('PASS: all 6 FSRS-lite DSR and study-plan invariant tests passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
