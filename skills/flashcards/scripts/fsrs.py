#!/usr/bin/env python3
"""Clean-room FSRS-lite (DSR: Difficulty, Stability, Retrievability) scheduler & study-plan validator.

Implements the power forgetting curve and DSR memory state updates (Ye et al., FSRS-4/6)
with Myelinate's honest-evidence invariants:
- `hinted-correct` and `self-assessed` never advance stability or interval (exposure != mastery).
- `revealed` and `incorrect` trigger a lapse branch and cap next review at <= 1 day.
- Exam-horizon clamping keeps the final review 1-2 days before the exam (Cepeda et al. 2008).
- Study-plan validation checks real available hours and protects >= 7 hours of sleep.

Standard library only; no network, no external dependencies.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
import math
import sys
from typing import Any

# Clean-room FSRS-4/6 default weights (standard public priors, 17 parameters).
DEFAULT_WEIGHTS: tuple[float, ...] = (
    0.40255,  # w0: initial stability for Again
    1.18385,  # w1: initial stability for Hard
    3.173,    # w2: initial stability for Good
    15.69105, # w3: initial stability for Easy
    7.1949,   # w4: initial difficulty anchor
    0.5345,   # w5: initial difficulty grade slope
    1.4604,   # w6: difficulty delta per rating
    0.0046,   # w7: difficulty mean reversion weight
    1.54575,  # w8: recall stability exp factor
    0.1192,   # w9: recall stability decay exponent
    1.01925,  # w10: recall retrievability gain
    1.9395,   # w11: lapse stability base
    0.11,     # w12: lapse difficulty exponent
    0.29605,  # w13: lapse stability exponent
    2.2698,   # w14: lapse retrievability gain
    0.2315,   # w15: Hard penalty
    2.9898,   # w16: Easy bonus
)

S_MIN = 0.1
S_MAX = 36500.0
D_MIN = 1.0
D_MAX = 10.0

OUTCOME_TO_GRADE = {
    'incorrect': 1,        # Again (lapse)
    'revealed': 1,         # Again (lapse; revealed is not mastery)
    'hinted-correct': 0,   # Special: hold state, never advance interval
    'self-assessed': 0,    # Special: hold state, never advance interval
    'unassisted-hard': 2,  # Hard
    'unassisted-correct': 3,  # Good
    'unassisted-easy': 4,  # Easy
}


@dataclass
class DSRState:
    difficulty: float = 5.0
    stability: float = 1.0
    retrievability_target: float = 0.90
    reps: int = 0
    lapses: int = 0
    interval_days: int = 1


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def retrievability(elapsed_days: float, stability: float) -> float:
    """FSRS-4 power forgetting curve: R(t, S) = (1 + t / (9 * S))^-1."""
    if stability <= 0:
        return 0.0
    t = max(0.0, float(elapsed_days))
    return (1.0 + t / (9.0 * stability)) ** -1.0


def optimal_interval(target_r: float, stability: float) -> float:
    """Inverse forgetting curve: I(r, S) = 9 * S * (1/r - 1)."""
    r = clamp(target_r, 0.70, 0.98)
    s = max(S_MIN, stability)
    return 9.0 * s * (1.0 / r - 1.0)


def initial_stability(grade: int, w: tuple[float, ...] = DEFAULT_WEIGHTS) -> float:
    idx = int(clamp(grade, 1, 4)) - 1
    return clamp(w[idx], S_MIN, S_MAX)


def initial_difficulty(grade: int, w: tuple[float, ...] = DEFAULT_WEIGHTS) -> float:
    g = int(clamp(grade, 1, 4))
    d0 = w[4] - math.exp(w[5] * (g - 1)) + 1.0
    return clamp(d0, D_MIN, D_MAX)


def next_difficulty(d: float, grade: int, w: tuple[float, ...] = DEFAULT_WEIGHTS) -> float:
    """FSRS-6 difficulty update with linear damping and mean reversion toward D_0(4)."""
    g = int(clamp(grade, 1, 4))
    delta_d = -w[6] * (g - 3)
    d_star = d + delta_d * (10.0 - d) / 9.0
    d_prime = w[7] * initial_difficulty(4, w) + (1.0 - w[7]) * d_star
    return clamp(d_prime, D_MIN, D_MAX)


def next_recall_stability(
    d: float,
    s: float,
    r: float,
    grade: int,
    w: tuple[float, ...] = DEFAULT_WEIGHTS,
) -> float:
    """Stability increase after an unassisted recall (Hard=2, Good=3, Easy=4)."""
    hard_penalty = w[15] if grade == 2 else 1.0
    easy_bonus = w[16] if grade == 4 else 1.0
    factor = (
        math.exp(w[8])
        * (11.0 - d)
        * (s ** -w[9])
        * (math.exp(w[10] * (1.0 - r)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return clamp(s * (1.0 + max(0.0, factor)), S_MIN, S_MAX)


def next_lapse_stability(
    d: float,
    s: float,
    r: float,
    w: tuple[float, ...] = DEFAULT_WEIGHTS,
) -> float:
    """Post-lapse stability (never exceeds pre-lapse stability)."""
    s_new = (
        w[11]
        * (d ** -w[12])
        * ((s + 1.0) ** w[13] - 1.0)
        * math.exp(w[14] * (1.0 - r))
    )
    return clamp(min(s, s_new), S_MIN, S_MAX)


def clamp_to_exam_horizon(
    raw_interval_days: int,
    days_to_exam: int | None,
) -> int:
    """Clamp interval so the learner reviews 1-2 days before an upcoming exam (Cepeda 2008)."""
    ivl = max(1, int(raw_interval_days))
    if days_to_exam is None:
        return ivl
    if days_to_exam <= 1:
        return 1
    if days_to_exam <= 3:
        return min(ivl, max(1, days_to_exam - 1))
    # Cepeda et al. (2008): ~20-40% of short horizons, capped at exam - 1 day.
    horizon_cap = max(1, min(days_to_exam - 1, math.ceil(days_to_exam * 0.40)))
    return min(ivl, horizon_cap)


def review(
    state: DSRState | None,
    outcome: str,
    elapsed_days: float = 1.0,
    days_to_exam: int | None = None,
    target_r: float | None = None,
    today: date | None = None,
    w: tuple[float, ...] = DEFAULT_WEIGHTS,
) -> dict[str, Any]:
    """Update a topic's DSR state from an honest attempt outcome and compute next review date."""
    if outcome not in OUTCOME_TO_GRADE:
        raise ValueError(f'Unknown attempt outcome: {outcome!r}')
    grade = OUTCOME_TO_GRADE[outcome]
    cur = state if state is not None else DSRState()
    r_target = clamp(target_r if target_r is not None else cur.retrievability_target, 0.70, 0.98)
    now = today or date.today()

    if grade == 0:
        # Myelinate invariant: hinted-correct or self-assessed NEVER advances interval or stability.
        held_interval = clamp_to_exam_horizon(max(1, cur.interval_days), days_to_exam)
        new_state = DSRState(
            difficulty=round(cur.difficulty, 4),
            stability=round(cur.stability, 4),
            retrievability_target=round(r_target, 4),
            reps=cur.reps,
            lapses=cur.lapses,
            interval_days=held_interval,
        )
    elif cur.reps == 0:
        d0 = initial_difficulty(grade, w)
        s0 = initial_stability(grade, w)
        lapses = cur.lapses + (1 if grade == 1 else 0)
        raw_ivl = 1 if grade == 1 else max(1, round(optimal_interval(r_target, s0)))
        ivl = clamp_to_exam_horizon(raw_ivl, days_to_exam)
        new_state = DSRState(
            difficulty=round(d0, 4),
            stability=round(s0, 4),
            retrievability_target=round(r_target, 4),
            reps=cur.reps + 1,
            lapses=lapses,
            interval_days=ivl,
        )
    else:
        r_now = retrievability(elapsed_days, cur.stability)
        d_next = next_difficulty(cur.difficulty, grade, w)
        if grade == 1:
            s_next = next_lapse_stability(cur.difficulty, cur.stability, r_now, w)
            raw_ivl = 1
            lapses = cur.lapses + 1
        else:
            s_next = next_recall_stability(cur.difficulty, cur.stability, r_now, grade, w)
            raw_ivl = max(cur.interval_days + 1 if grade >= 3 else 1, round(optimal_interval(r_target, s_next)))
            lapses = cur.lapses
        ivl = clamp_to_exam_horizon(raw_ivl, days_to_exam)
        new_state = DSRState(
            difficulty=round(d_next, 4),
            stability=round(s_next, 4),
            retrievability_target=round(r_target, 4),
            reps=cur.reps + 1,
            lapses=lapses,
            interval_days=ivl,
        )

    next_date = (now + timedelta(days=new_state.interval_days)).isoformat()
    return {
        'outcome': outcome,
        'fsrs': asdict(new_state),
        'interval_days': new_state.interval_days,
        'next_review': next_date,
    }


def validate_study_plan(plan: dict[str, Any]) -> list[str]:
    """Deterministically validate a structured study plan against Myelinate scheduling invariants."""
    errors: list[str] = []
    avail = float(plan.get('available_hours', 0))
    sleep_h = float(plan.get('sleep_hours_per_night', 0))
    days_to_exam = int(plan.get('days_to_exam', 0))
    blocks = plan.get('blocks', [])
    if sleep_h < 7.0:
        errors.append(f'sleep_hours_per_night={sleep_h} violates >= 7h sleep protection (no all-nighters)')
    if not isinstance(blocks, list) or not blocks:
        errors.append('blocks must be a non-empty list')
        return errors
    scheduled_hours = sum(float(b.get('minutes', 0)) for b in blocks) / 60.0
    if avail > 0 and scheduled_hours > avail + 1e-6:
        errors.append(f'scheduled {scheduled_hours:.2f}h exceeds available_hours {avail:.2f}h')
    for i, b in enumerate(blocks):
        mins = float(b.get('minutes', 0))
        if mins < 15 or mins > 60:
            errors.append(f'block[{i}] duration {mins}m outside 15-60m focused range')
        day_offset = int(b.get('day_offset', 0))
        if days_to_exam > 0 and day_offset > days_to_exam:
            errors.append(f'block[{i}] day_offset {day_offset} is past days_to_exam={days_to_exam}')
        if b.get('activity_kind') == 'passive-reread':
            errors.append(f'block[{i}] schedules passive rereading instead of active retrieval/practice')
    if plan.get('has_drop_list') is False and avail > 0 and scheduled_hours >= avail * 0.85:
        errors.append('tight schedule missing explicit drop list ("if time runs out, drop")')
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description='Compute FSRS-lite DSR next review date for a topic.')
    ap.add_argument('--outcome', required=True, choices=sorted(OUTCOME_TO_GRADE))
    ap.add_argument('--difficulty', type=float, default=5.0)
    ap.add_argument('--stability', type=float, default=1.0)
    ap.add_argument('--reps', type=int, default=0)
    ap.add_argument('--lapses', type=int, default=0)
    ap.add_argument('--interval', type=int, default=1)
    ap.add_argument('--elapsed', type=float, default=1.0)
    ap.add_argument('--days-to-exam', type=int, default=None)
    ap.add_argument('--target-r', type=float, default=0.90)
    ap.add_argument('--today', default=None, help='ISO YYYY-MM-DD')
    args = ap.parse_args()
    st = DSRState(
        difficulty=args.difficulty,
        stability=args.stability,
        retrievability_target=args.target_r,
        reps=args.reps,
        lapses=args.lapses,
        interval_days=args.interval,
    )
    today = date.fromisoformat(args.today) if args.today else date.today()
    out = review(st, args.outcome, elapsed_days=args.elapsed, days_to_exam=args.days_to_exam, today=today)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
