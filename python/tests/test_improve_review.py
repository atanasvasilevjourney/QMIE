"""One-variable review CLI: propose, never apply."""
from __future__ import annotations

from pathlib import Path

from improve.review import (
    _towards_goal,
    already_proposed,
    journal_snapshot,
    load_simple_yaml,
    pick_knob,
    run_review,
)


def test_yaml_nested_scalars(tmp_path: Path):
    p = tmp_path / "g.yaml"
    p.write_text("success:\n  min_win_pct: 48.0\nreview:\n  min_closed_fills: 30\n")
    d = load_simple_yaml(p)
    assert d["success"]["min_win_pct"] == 48.0
    assert d["review"]["min_closed_fills"] == 30


def test_insufficient_sample_proposes_nothing(tmp_path: Path):
    goals = tmp_path / "goals.yaml"
    goals.write_text(
        "success:\n  min_win_pct: 48.0\n  min_expectancy_r: 0.15\n"
        "failure:\n  win_pct_below: 40.0\n  expectancy_r_below: 0.0\n"
        "review:\n  min_closed_fills: 30\n"
    )
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text("sig_min_adx: 0.0\nalloc_top_long: 3\n")
    out_dir = tmp_path / "reviews"
    path = run_review(
        goals_path=goals,
        baseline_path=baseline,
        reviews_dir=out_dir,
        db_path=None,
    )
    body = path.read_text()
    assert "verdict: insufficient_sample" in body
    assert "proposed_knob: none" in body
    assert "Do not change anything" in body


def test_short_of_goal_proposes_first_matching_knob(tmp_path: Path):
    goals = tmp_path / "goals.yaml"
    goals.write_text(
        "success:\n  min_win_pct: 48.0\n  min_expectancy_r: 0.15\n"
        "failure:\n  win_pct_below: 40.0\n  expectancy_r_below: 0.0\n"
        "review:\n  min_closed_fills: 2\n"
    )
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text("sig_min_adx: 0.0\nalloc_top_long: 3\n")
    # journal with 3 closed losers so sample is enough but short of goal
    db = tmp_path / "qmie.db"
    import sqlite3
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE signals (id INTEGER PRIMARY KEY, grade TEXT);
        CREATE TABLE fills (
            id INTEGER PRIMARY KEY, signal_id INTEGER,
            outcome TEXT, realized_r REAL
        );
        INSERT INTO signals VALUES (1, 'A'), (2, 'A'), (3, 'A');
        INSERT INTO fills VALUES (1, 1, 'LOSS', -1.0),
                                 (2, 2, 'LOSS', -0.5),
                                 (3, 3, 'WIN', 1.0);
        """
    )
    con.commit()
    con.close()
    out_dir = tmp_path / "reviews"
    path = run_review(
        goals_path=goals,
        baseline_path=baseline,
        reviews_dir=out_dir,
        db_path=db,
    )
    body = path.read_text()
    assert "proposed_knob: sig_min_adx" in body
    assert "proposed_from: 0.0" in body
    assert "proposed_to: 20.0" in body
    assert "applied: false" in body


def test_pick_knob_skips_already_proposed(tmp_path: Path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "2026-01-01.md").write_text("proposed_knob: sig_min_adx\n")
    used = already_proposed(reviews)
    knob = pick_knob({"sig_min_adx": 0.0, "alloc_top_long": 3}, used)
    assert knob is not None
    assert knob.name == "alloc_top_long"


def test_pick_knob_scan_timeframes_first_when_live_default():
    knob = pick_knob({"scan_timeframes": "1h,4h", "sig_min_adx": 0.0}, set())
    assert knob is not None
    assert knob.name == "scan_timeframes"
    assert knob.to_value == "4h"


def test_towards_goal_success():
    goals = {
        "success": {"min_win_pct": 48.0, "min_expectancy_r": 0.15},
        "failure": {"win_pct_below": 40.0, "expectancy_r_below": 0.0},
        "review": {"min_closed_fills": 3},
    }
    stats = {"closed": 10, "win_pct": 55.0, "avg_realized_r": 0.4}
    assert _towards_goal(stats, goals) == "success"


def test_journal_snapshot_missing_db(tmp_path: Path):
    snap = journal_snapshot(tmp_path / "nope.db")
    assert snap["available"] is False
    assert snap["closed"] == 0
