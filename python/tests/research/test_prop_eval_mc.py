from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.prop_eval_mc import EvalRules, simulate_one_attempt


def test_simulate_pass_on_constant_positive():
    r = np.full(30, 0.005)
    outcome, days = simulate_one_attempt(r, risk_scale=1.0, rules=EvalRules(profit_target_pct=0.10))
    assert outcome == "pass"
    assert days < 30


def test_simulate_fail_on_crash():
    r = np.concatenate([np.full(5, 0.01), np.array([-0.12])])
    outcome, _ = simulate_one_attempt(r, risk_scale=1.0, rules=EvalRules())
    assert outcome == "fail"
