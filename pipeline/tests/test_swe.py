"""Fast checks of the flood solver on small grids. The full P0 run is pipeline/scripts/p0_solver.py."""

import numpy as np
import torch

from moraine import benchmarks as b
from moraine.swe import G, Solver


def test_ritter_exact_solution_conserves_water():
    # The water that left the reservoir (h0 * c0 * t) is exactly the water in the moving wave
    t, dx = 20.0, 0.05
    x = np.arange(-600, 600, dx) + dx / 2
    released = b.H0 * np.sqrt(G * b.H0) * t
    in_wave = b.ritter_depth(x, t)[x > -np.sqrt(G * b.H0) * t].sum() * dx
    assert abs(in_wave - released) / released < 1e-4


def test_order_of_accuracy_reads_a_slope():
    assert abs(b.order_of_accuracy([10, 5, 2.5], [0.04, 0.01, 0.0025]) - 2.0) < 1e-12


def test_small_dam_break_matches_ritter_and_keeps_its_water():
    r = b.ritter_1d(10.0)
    assert r["error"] < 0.03
    assert r["volume_change"] < 1e-12
    assert r["clamped_share"] == 0.0
    assert abs(b.ritter_front(b.T_END) - r["front"]) < 6 * 10.0


def test_dam_break_along_y_is_the_transpose_of_along_x():
    along_x = b.ritter_1d(20.0)
    along_y = b.ritter_1d(20.0, axis="y")
    assert np.array_equal(along_x["full"], along_y["full"].T)


def test_dam_break_down_a_slope_follows_the_moving_frame_solution():
    r = b.ritter_1d(10.0, slope=0.3, upstream=300.0, downstream=450.0, t_end=10.0)
    assert r["error"] < 0.05


def test_lake_at_rest_over_a_covered_bed_stays_still():
    r = b.lake_at_rest(10.0, n=20, dx=50.0, t_end=30.0)
    assert r["dry_share"] == 0.0
    assert r["max_speed"] < 1e-10
    assert r["max_surface_change"] < 1e-10


def test_dry_bed_stays_dry_and_time_steps_stop_on_time():
    solver = Solver(np.zeros((5, 9)), 10.0)
    s = solver.state(np.zeros((4, 8)))
    s.w[1, 3] += 1.0  # a single wet cell in a dry basin
    s.w = s.w.clone()
    solver.run(s, 2.5)
    assert abs(s.t - 2.5) < 1e-12
    assert float(solver.depth(s).min()) >= 0.0
    assert abs(solver.volume(s) - 100.0) < 1e-9


def test_float32_runs():
    r = b.ritter_1d(20.0, dtype=torch.float32)
    assert r["error"] < 0.05
