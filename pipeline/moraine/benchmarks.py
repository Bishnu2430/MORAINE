"""Exact solutions and test set-ups for checking the flood solver (P0 solver spike)."""

from __future__ import annotations

import time

import numpy as np
import torch

from .swe import G, Solver

H0 = 10.0  # m of water behind the dam
T_END = 20.0  # s after the dam fails
FRONT_DEPTH = 0.1  # m; the flood front is where the water first reaches 10 cm, 1% of the dam's depth
LAKE_ELEVATION = 5200.0  # m; South Lhonak's surface, the worst case for float32 rounding


def ritter_depth(x, t: float, h0: float = H0) -> np.ndarray:
    """Ritter (1892): depth at x metres and t seconds after a dam at x = 0, holding water h0 deep on
    x < 0, vanishes instantly over a dry, flat, frictionless bed."""
    c0 = np.sqrt(G * h0)
    xi = np.asarray(x, dtype=float) / t
    fan = (2 * c0 - xi) ** 2 / (9 * G)
    return np.where(xi <= -c0, h0, np.where(xi >= 2 * c0, 0.0, fan))


def ritter_average(lo, size: float, t: float, h0: float = H0, samples: int = 32) -> np.ndarray:
    """Exact depth averaged over cells [lo, lo + size), for a fair comparison with cell averages."""
    offsets = (np.arange(samples) + 0.5) / samples * size
    return ritter_depth(np.asarray(lo)[..., None] + offsets, t, h0).mean(axis=-1)


def ritter_front(t: float, depth: float = FRONT_DEPTH, h0: float = H0) -> float:
    """Where the exact solution is `depth` deep at the leading edge."""
    return t * (2 * np.sqrt(G * h0) - 3 * np.sqrt(G * depth))


def front_position(x: np.ndarray, h: np.ndarray, depth: float = FRONT_DEPTH) -> float:
    """Furthest point downstream where h reaches `depth`, interpolated between cell centres."""
    i = int(np.nonzero(h >= depth)[0][-1])
    if i + 1 == len(h):
        return float(x[i])
    return float(x[i] + (h[i] - depth) / (h[i] - h[i + 1]) * (x[i + 1] - x[i]))


def depth_error(h: np.ndarray, exact: np.ndarray, xi: np.ndarray, t: float, h0: float = H0) -> float:
    """Total |h - exact| as a share of the exact water in the moving wave (from the rarefaction head
    at -c0 t to the dry front at 2 c0 t). xi is each cell's distance downstream of the dam."""
    c0 = np.sqrt(G * h0)
    wave = (xi >= -c0 * t) & (xi <= 2 * c0 * t)
    return float(np.abs(h - exact).sum() / exact[wave].sum())


def order_of_accuracy(sizes, errors) -> float:
    """Slope of log(error) against log(cell size): 1 means the error halves when the cells halve."""
    return float(np.polyfit(np.log(sizes), np.log(errors), 1)[0])


def _timed_run(solver: Solver, state, t_end: float) -> dict:
    v0 = solver.volume(state)
    start = time.perf_counter()
    solver.run(state, t_end)
    seconds = time.perf_counter() - start
    return {
        "volume_change": abs(solver.volume(state) - v0) / v0,
        "clamped_share": solver.clamped_volume(state) / v0,
        "steps": state.steps,
        "cells": solver.cells,
        "seconds": seconds,
    }


def ritter_1d(dx: float, axis: str = "x", dtype=torch.float64, offset: float = 0.0, slope: float = 0.0,
              upstream: float = 600.0, downstream: float = 600.0, t_end: float = T_END, device: str = "cpu") -> dict:
    """Ritter dam break along one grid axis of a channel 4 cells wide, walls all round.

    With slope > 0 the bed falls by `slope` m per m downstream. The exact solution is then Ritter's,
    shifted downstream by g slope t² / 2: on a uniform frictionless slope all the water accelerates
    together at g slope, so in a frame moving with it the bed looks flat. Only cells that no wave from
    the upstream wall can have reached are scored.
    """
    n, width = int(round((upstream + downstream) / dx)), 4
    lo = np.arange(n) * dx - upstream
    x = lo + dx / 2
    depth = np.tile(np.where(x < 0, H0, 0.0), (width, 1))
    bed = np.tile(offset - slope * np.append(lo, lo[-1] + dx), (width + 1, 1))
    if axis == "y":
        depth, bed = depth.T, bed.T
    solver = Solver(bed, dx, dx, dtype=dtype, device=device)
    state = solver.state(depth)
    out = _timed_run(solver, state, t_end)
    h = solver.depth(state).double().cpu().numpy()
    shift = 0.5 * G * slope * t_end ** 2
    xi = x - shift  # distance downstream of the dam in the frame moving with the water
    exact = ritter_average(lo - shift, dx, t_end)
    scored = xi > -upstream + np.sqrt(G * H0) * t_end + 4 * dx
    out.update(x=x, xi=xi, h=h[0] if axis == "x" else h[:, 0], exact=exact, full=h)
    out["error"] = depth_error(out["h"][scored], exact[scored], xi[scored], t_end)
    out["front"] = front_position(xi, out["h"])
    out["front_1cm"] = front_position(xi, out["h"], 0.01)
    return out


def ritter_diagonal(dx: float = 5.0, half: float = 800.0, t_end: float = T_END, dtype=torch.float64,
                    offset: float = 0.0, device: str = "cpu") -> dict:
    """Ritter dam break with the dam along the grid diagonal x + y = 0, so the flood crosses the grid at 45°
    and both directions and their cross terms carry flow. Scored only in the central square that no wave
    reflected from the walls can reach by t_end."""
    n = int(round(2 * half / dx))
    lo = np.arange(n) * dx - half
    xc = lo + dx / 2
    X, Y = np.meshgrid(xc, xc)  # rows are y, columns are x
    s = X + Y
    depth = np.where(s < 0, H0, np.where(s == 0, H0 / 2, 0.0))  # cells the dam line cuts in half start half full
    solver = Solver(np.full((n + 1, n + 1), offset), dx, dx, dtype=dtype, device=device)
    state = solver.state(depth)
    out = _timed_run(solver, state, t_end)
    h = solver.depth(state).double().cpu().numpy()

    k = 8  # exact cell averages from k x k sample points per cell
    sub = (np.arange(k) + 0.5) / k * dx
    px = (lo[:, None] + sub).ravel()
    PX, PY = np.meshgrid(px, px)
    exact = ritter_depth((PX + PY) / np.sqrt(2), t_end).reshape(n, k, n, k).mean(axis=(1, 3))

    c0 = np.sqrt(G * H0)
    reach = half - 2 * c0 * t_end - 4 * dx  # wall reflections travel at most 2 c0
    core = (np.abs(X) < reach) & (np.abs(Y) < reach)
    xi = s / np.sqrt(2)
    out["error"] = depth_error(h[core], exact[core], xi[core], t_end)
    diag = np.arange(n)  # cells on the line x = y, where the distance downstream of the dam is sqrt(2) x
    out["front"] = front_position(np.sqrt(2) * xc, h[diag, diag])
    out.update(h=h, exact=exact, core=core)
    return out


def lake_bed(n: int = 100, dx: float = 10.0, offset: float = 0.0) -> np.ndarray:
    """A 1 km basin floor at the cell corners: rolling ground, two hills and a steep cone, 0.5-11 m high."""
    c = np.arange(n + 1) * dx
    X, Y = np.meshgrid(c, c)
    bed = 2 + 1.5 * np.sin(2 * np.pi * X / 400) * np.cos(2 * np.pi * Y / 300)
    bed += 5 * np.exp(-((X - 300) ** 2 + (Y - 650) ** 2) / (2 * 90 ** 2))
    bed += 4 * np.exp(-((X - 700) ** 2 + (Y - 300) ** 2) / (2 * 60 ** 2))
    bed += np.clip(9 - 9 * np.hypot(X - 600, Y - 700) / 40, 0, None)  # cone 9 m high, 40 m radius: 13° sides
    return offset + bed


def lake_at_rest(level: float, n: int = 100, dx: float = 10.0, t_end: float = 120.0, offset: float = 0.0,
                 shoreline: str = "pool", dtype=torch.float64, device: str = "cpu") -> dict:
    """Still water with its surface at `level` m above the basin floor. It must stay still."""
    solver = Solver(lake_bed(n, dx, offset), dx, dx, shoreline=shoreline, dtype=dtype, device=device)
    depth = solver.still_water(offset + level)
    state = solver.state(depth)
    wet, deep = depth > 0, depth > 0.1
    w0 = state.w.clone()
    out = _timed_run(solver, state, t_end)
    u, v = solver.velocity(state)
    speed = torch.hypot(u, v)
    out["max_speed"] = float(speed.max())
    out["max_speed_deep"] = float(speed[solver.depth(state) > 0.1].max())  # in water deeper than 10 cm now
    out["max_surface_change"] = float((state.w - w0)[wet].abs().max())
    out["max_surface_change_deep"] = float((state.w - w0)[deep].abs().max())  # where it started deeper than 10 cm
    out["dry_share"] = float((~wet).double().mean())
    return out


def thacker_bowl(dx: float = 25.0, a: float = 1000.0, h0: float = 10.0, offset: float = 500.0, orbits: float = 1.0,
                 shoreline: str = "pool", dtype=torch.float64, device: str = "cpu") -> dict:
    """Thacker (1981): a lens of water sloshing round a frictionless bowl shaped like a paraboloid.

    The bed is h0 (r^2 / a^2 - 1) at distance r from the bowl's centre (a = 1 km, h0 = 10 m: about
    1 degree at the rim). The water's flat surface tilts and turns, so its shoreline climbs and falls
    the bowl's sides all the way round. The exact answer at any time is the same lens, h0 deep and a
    wide, its centre circling `offset` m from the bowl's centre with period 2 pi a / sqrt(2 g h0).
    After whole orbits the water is back where it started.
    """
    half = 2 * a
    n = int(round(2 * half / dx))
    c = np.arange(n + 1) * dx - half
    X, Y = np.meshgrid(c, c)
    omega = np.sqrt(2 * G * h0) / a

    def exact(t: float, k: int = 8) -> np.ndarray:
        p = (c[:-1, None] + (np.arange(k) + 0.5) / k * dx).ravel()
        PX, PY = np.meshgrid(p, p)
        cx, cy = offset * np.cos(omega * t), offset * np.sin(omega * t)
        h = np.clip(h0 / a ** 2 * (a ** 2 - (PX - cx) ** 2 - (PY - cy) ** 2), 0, None)
        return h.reshape(n, k, n, k).mean(axis=(1, 3))

    start = exact(0.0)
    solver = Solver(h0 * ((X ** 2 + Y ** 2) / a ** 2 - 1), dx, dx, shoreline=shoreline, dtype=dtype, device=device)
    state = solver.state(start, hv=start * offset * omega)  # at t = 0 the whole lens moves along +y
    t_end = orbits * 2 * np.pi / omega
    out = _timed_run(solver, state, t_end)
    h = solver.depth(state).double().cpu().numpy()
    end = exact(t_end)
    wet, wet_exact = h > 0.01, end > 0.01
    out.update(h=h, exact=end, t_end=t_end)
    out["error"] = float(np.abs(h - end).sum() / end.sum())
    out["iou"] = float((wet & wet_exact).sum() / (wet | wet_exact).sum())
    return out
