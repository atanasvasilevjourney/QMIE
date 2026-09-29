import pandas as pd

from research.strategy_performance import summarize_aa


def test_summarize_aa_winning_sample():
    df = pd.DataFrame(
        {
            "grade": ["A", "A", "A+"],
            "outcome": ["WIN", "WIN", "LOSS"],
            "rr_ratio": [1.67, 1.67, 1.67],
            "realized_r": [1.67, 1.67, -1.0],
            "timestamp": pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC"),
        }
    )
    s = summarize_aa(df)
    assert s is not None
    assert s.closed == 3
    assert s.win_pct > 60
