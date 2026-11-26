"""Shallow-water flood solver: the second-order central-upwind scheme of Kurganov and Petrova (2007).

The unknowns are cell averages of the water surface w = h + B and the discharges hu and hv on a
regular grid. The bed B is given at cell corners and treated as bilinear inside each cell, as in
the paper. Two properties matter on steep Himalayan terrain, and the P0 spike checks both:

- depths never go negative, as long as each time step stays within a quarter of the stability
  limit (the default CFL number of 0.25);
- a lake at rest stays exactly at rest, over any bed and with islands (the shoreline change below).

One change from the paper: the face values of velocity are reconstructed from cell velocities rather
than face discharges from cell discharges. A face velocity then never exceeds its neighbouring
cells', which stops millimetre films of water racing ahead of a dry-bed flood front faster than the
physics allows (P0 finding; it also cut the time steps needed near shorelines about fivefold).

Shorelines. Where a lake's edge crosses a cell, the 2007 paper tilts that cell's water surface down
to the bed, and still water starts to move (P0 measured about 2 m/s). Following the idea of
Bollermann, Chen, Kurganov and Noelle (2013), such a cell is instead given a flat water surface at
the level that holds its water: its "pool level". Each cell's bed is split into four quarters at its
corner elevations to turn a volume of water into a level, and the same level serves both directions,
so a still lake with islands stays exactly still in 2D. A partly dry cell uses its pool level only
when its wet neighbours' surfaces are level with it to within a tenth of the cell's own relief, as
at a lake edge or against a valley wall. Moving water keeps the 2007 reconstruction: on Thacker's
sloshing bowl, pooling every partly dry cell let thin water creep across the dry slope (wet area
twice the true one), because the four flat quarters of neighbouring cells meet as flat terraces.
A hard switch, not a gradual blend: a blend let rounding noise in a still lake feed on itself. The
bed-slope source is written so that it balances the pressure across whichever surface a cell uses.
Pool faces never hold more water than the cell has, so the 2007 positivity argument, and its
time-step limit, carry over unchanged.

Written in PyTorch so the same code runs on the laptop CPU in float64 for checks and on a Colab
GPU for the real runs. Friction, rain and open boundaries come in P2; for now every side is a wall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn.functional as F

G = 9.81  # m/s²
GHOST = 2  # ghost cells on each side, enough for the piecewise-linear reconstruction
POOL_TOLERANCE = 0.1  # pool a partly dry cell when wet neighbours' surfaces differ from its own by at most this share of its relief


@dataclass
class State:
    """Cell averages on the interior grid, each of shape (ny, nx). Row index is y, column index is x."""

    w: torch.Tensor  # cell-average bed plus cell-average depth (m); the water surface where a cell is fully wet
    hu: torch.Tensor  # discharge per metre of width along x (m²/s)
    hv: torch.Tensor  # discharge per metre of width along y (m²/s)
    t: float = 0.0  # simulated time (s)
    steps: int = 0
    clamped: torch.Tensor | None = None  # depth (m, summed over cells) added by the safety clamp; should stay ~0


def _minmod(a: torch.Tensor, b: torch.Tensor, c: torch.Tensor) -> torch.Tensor:
    lo = torch.minimum(torch.minimum(a, b), c)
    hi = torch.maximum(torch.maximum(a, b), c)
    return torch.where(lo > 0, lo, torch.where(hi < 0, hi, torch.zeros_like(lo)))


def _mirror(q: torch.Tensor, sign_x: float = 1.0, sign_y: float = 1.0) -> torch.Tensor:
    """Add GHOST cells on every side, mirrored across the walls.

    sign_x = -1 flips the value across the left and right walls (for hu), sign_y across the bottom and top (for hv).
    """
    def edge(part, sign):
        return part if sign == 1.0 else part * sign

    q = torch.cat([edge(torch.flip(q[:, :GHOST], [1]), sign_x), q, edge(torch.flip(q[:, -GHOST:], [1]), sign_x)],
                  dim=1)
    return torch.cat([edge(torch.flip(q[:GHOST], [0]), sign_y), q, edge(torch.flip(q[-GHOST:], [0]), sign_y)], dim=0)


def _velocity(h: torch.Tensor, q: torch.Tensor, eps: float) -> torch.Tensor:
    """q / h, smoothly damped to zero in water shallower than eps**(1/4) (Kurganov and Petrova, eq. 2.17)."""
    h2 = h * h
    h4 = h2 * h2
    return math.sqrt(2.0) * h * q / torch.sqrt(h4 + torch.clamp(h4, min=eps))


def _sweep(w, level, pool, un, ut, bed_faces, d, theta):
    """Fluxes across the faces normal to the last axis, and the bed-slope source term.

    w, un, ut: (rows, n + 4) padded cell values; un is the velocity across the faces, ut along them.
    level, pool: each cell's pool level, and whether the cell uses it as a flat water surface.
    bed_faces: (rows, n + 5) bed elevation at the midpoint of every padded face; face i lies between
    padded cells i - 1 and i.
    Returns the three fluxes on the n + 1 interior faces (rows, n + 1), the source for the n interior
    cells (rows, n) and the fastest wave speed (a 0-d tensor).
    """

    def faces(q):
        # Generalized minmod slope in padded cells 1 .. n + 2, then values at each cell's low and high face
        mid = q[:, 1:-1]
        half = 0.5 * _minmod(theta * (mid - q[:, :-2]), 0.5 * (q[:, 2:] - q[:, :-2]), theta * (q[:, 2:] - mid))
        return mid - half, mid + half

    wc = w[:, 1:-1]
    w_lo, w_hi = faces(w)
    b_lo, b_hi = bed_faces[:, 1:-2], bed_faces[:, 2:-1]

    # Positivity correction: if the reconstructed surface dips below the bed at one face, tilt it so
    # that face is exactly dry and the cell keeps its volume (section 3.1 of the paper)
    low = w_hi < b_hi
    w_hi, w_lo = torch.where(low, b_hi, w_hi), torch.where(low, 2 * wc - b_hi, w_lo)
    low = ~low & (w_lo < b_lo)
    w_lo, w_hi = torch.where(low, b_lo, w_lo), torch.where(low, 2 * wc - b_lo, w_hi)
    # Pool cells: a flat surface at the pool level instead
    pool_c, level_c = pool[:, 1:-1], level[:, 1:-1]
    s_lo, s_hi = torch.where(pool_c, level_c, w_lo), torch.where(pool_c, level_c, w_hi)
    h_lo = torch.clamp(s_lo - b_lo, min=0)
    h_hi = torch.clamp(s_hi - b_hi, min=0)

    # Velocities at the faces, zero where a face is dry; discharges follow from depth times velocity
    un_lo, un_hi = faces(un)
    ut_lo, ut_hi = faces(ut)
    zero = torch.zeros_like(h_lo)
    un_lo, un_hi = torch.where(h_lo > 0, un_lo, zero), torch.where(h_hi > 0, un_hi, zero)
    ut_lo, ut_hi = torch.where(h_lo > 0, ut_lo, zero), torch.where(h_hi > 0, ut_hi, zero)
    qn_lo, qn_hi, qt_lo, qt_hi = h_lo * un_lo, h_hi * un_hi, h_lo * ut_lo, h_hi * ut_hi

    # Interior face k joins the high side of reconstructed cell k to the low side of cell k + 1
    hL, hR = h_hi[:, :-1], h_lo[:, 1:]
    wL, wR = (b_hi + h_hi)[:, :-1], (b_lo + h_lo)[:, 1:]  # the bed is shared at a face, so these differ by depth only
    uL, uR = un_hi[:, :-1], un_lo[:, 1:]
    vL, vR = ut_hi[:, :-1], ut_lo[:, 1:]
    qL, qR = qn_hi[:, :-1], qn_lo[:, 1:]
    pL, pR = qt_hi[:, :-1], qt_lo[:, 1:]
    cL, cR = torch.sqrt(G * hL), torch.sqrt(G * hR)
    ap = torch.clamp(torch.maximum(uL + cL, uR + cR), min=0)
    am = torch.clamp(torch.minimum(uL - cL, uR - cR), max=0)
    span = ap - am
    wet = span > 0
    inv = torch.where(wet, 1.0 / torch.where(wet, span, torch.ones_like(span)), torch.zeros_like(span))

    def flux(fL, fR, sL, sR):
        return (ap * fL - am * fR + ap * am * (sR - sL)) * inv

    f_w = flux(qL, qR, wL, wR)
    f_n = flux(qL * uL + 0.5 * G * hL * hL, qR * uR + 0.5 * G * hR * hR, qL, qR)
    f_t = flux(qL * vL, qR * vR, pL, pR)

    # Bed slope in the n interior cells, written as the pressure difference across the cell minus the
    # push of the surface slope, so a flat surface (wet or pool) feels no net force. Where the surface
    # meets the water at both faces this equals the paper's -g (h_lo + h_hi) / 2 * (b_hi - b_lo) / d.
    src = 0.5 * G * (h_hi * h_hi - h_lo * h_lo - (h_lo + h_hi) * (s_hi - s_lo))[:, 1:-1] / d
    return f_w, f_n, f_t, src, torch.maximum(ap.max(), -am.min())


class Solver:
    """A closed rectangular basin with walls on all four sides.

    bed: elevation at the cell corners, shape (ny + 1, nx + 1), in metres. dx and dy are the cell size in metres.
    h_dry: depth (m) below which velocities are smoothly damped to zero.
    shoreline: "pool" (default) or "kp07", the paper's original tilted surface, kept for comparison.
    """

    def __init__(self, bed, dx: float, dy: float | None = None, *, cfl: float = 0.25, theta: float = 1.3,
                 h_dry: float = 1e-3, shoreline: str = "pool", dtype: torch.dtype = torch.float64,
                 device: str = "cpu"):
        if shoreline not in ("pool", "kp07"):
            raise ValueError(f"shoreline must be 'pool' or 'kp07', not {shoreline!r}")
        self.shoreline = shoreline
        b = torch.as_tensor(bed, dtype=dtype, device=device)
        self.ny, self.nx = b.shape[0] - 1, b.shape[1] - 1
        self.dx, self.dy = float(dx), float(dy if dy is not None else dx)
        self.cfl, self.theta, self.eps = cfl, theta, h_dry ** 4
        self.dtype, self.device = dtype, device
        corners = F.pad(b[None, None], (GHOST,) * 4, mode="reflect")[0, 0]  # bed mirrored across the walls
        self.bx = 0.5 * (corners[:-1] + corners[1:])  # bed at the midpoints of the x-faces, (ny + 4, nx + 5)
        self.by = 0.5 * (corners[:, :-1] + corners[:, 1:])  # bed at the midpoints of the y-faces, (ny + 5, nx + 4)
        self.bc_padded = 0.5 * (self.bx[:, :-1] + self.bx[:, 1:])  # cell centres, (ny + 4, nx + 4)
        self.bc = self.bc_padded[GHOST:-GHOST, GHOST:-GHOST]  # (ny, nx)
        # Each cell's bed as four quarters at its corner elevations, sorted: z[0] <= ... <= z[3].
        # A flat pool at level L then holds an average depth V(L) = mean(max(L - z_k, 0)).
        z = torch.stack([corners[:-1, :-1], corners[:-1, 1:], corners[1:, :-1], corners[1:, 1:]]).sort(dim=0).values
        self.z = z
        self.z_sum = z.cumsum(dim=0)  # z_sum[m - 1] = sum of the m lowest corners
        # Depth held when the pool reaches the 2nd, 3rd and 4th corner; past the last the cell is fully wet
        self.v_break = torch.stack([(k * z[k] - self.z_sum[k - 1]) / 4 for k in (1, 2, 3)])
        self.relief = z[3] - z[0]

    @property
    def cells(self) -> int:
        return self.nx * self.ny

    def state(self, depth, hu=None, hv=None) -> State:
        h = torch.clamp(torch.as_tensor(depth, dtype=self.dtype, device=self.device), min=0)
        if h.shape != self.bc.shape:
            raise ValueError(f"depth has shape {tuple(h.shape)}, the grid is {tuple(self.bc.shape)}")
        zeros = torch.zeros_like(h)
        hu = zeros.clone() if hu is None else torch.as_tensor(hu, dtype=self.dtype, device=self.device)
        hv = zeros.clone() if hv is None else torch.as_tensor(hv, dtype=self.dtype, device=self.device)
        return State(self.bc + h, hu, hv, clamped=torch.zeros((), dtype=torch.float64, device=self.device))

    def still_water(self, level) -> torch.Tensor:
        """Cell-average depths of still water with its surface at `level` m; pass to state() for a lake at rest."""
        z = self.z[:, GHOST:-GHOST, GHOST:-GHOST]
        level = torch.as_tensor(level, dtype=self.dtype, device=self.device)
        partial = torch.clamp(level - z, min=0).mean(dim=0)
        return torch.where(level >= z[3], level - self.bc, partial)

    def _pool_level(self, h: torch.Tensor) -> torch.Tensor:
        """Inverse of V on the padded grid: the flat level that holds an average depth h in each cell."""
        m = 1 + (h >= self.v_break).sum(dim=0)  # corners under water
        below = torch.gather(self.z_sum, 0, (m - 1)[None])[0]
        return (4 * h + below) / m

    def depth(self, s: State) -> torch.Tensor:
        return torch.clamp(s.w - self.bc, min=0)

    def velocity(self, s: State) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.depth(s)
        return _velocity(h, s.hu, self.eps), _velocity(h, s.hv, self.eps)

    def volume(self, s: State) -> float:
        """Water volume in m³, summed in float64."""
        return float(self.depth(s).double().sum()) * self.dx * self.dy

    def clamped_volume(self, s: State) -> float:
        """Water (m³) the safety clamp added to stop depths going negative. A correct run keeps this near zero."""
        return float(s.clamped) * self.dx * self.dy

    def _rates(self, w, hu, hv):
        k = GHOST
        wp = _mirror(w)
        hp = torch.clamp(wp - self.bc_padded, min=0)
        up = _velocity(hp, _mirror(hu, sign_x=-1.0), self.eps)
        vp = _velocity(hp, _mirror(hv, sign_y=-1.0), self.eps)
        level, pool = self._pools(wp, hp)
        fw, fu, fv, su, ax = _sweep(wp[k:-k], level[k:-k], pool[k:-k], up[k:-k], vp[k:-k], self.bx[k:-k], self.dx,
                                    self.theta)
        # The y-direction is the same sweep on the transposed grid, with u and v swapping roles
        gw, gv, gu, sv, ay = _sweep(wp[:, k:-k].T, level[:, k:-k].T, pool[:, k:-k].T, vp[:, k:-k].T,
                                    up[:, k:-k].T, self.by[:, k:-k].T, self.dy, self.theta)
        dw = -(fw[:, 1:] - fw[:, :-1]) / self.dx - (gw[:, 1:] - gw[:, :-1]).T / self.dy
        dhu = -(fu[:, 1:] - fu[:, :-1]) / self.dx - (gu[:, 1:] - gu[:, :-1]).T / self.dy + su
        dhv = -(fv[:, 1:] - fv[:, :-1]) / self.dx - (gv[:, 1:] - gv[:, :-1]).T / self.dy + sv.T
        return dw, dhu, dhv, torch.stack([ax, ay])

    def _pools(self, wp, hp):
        """Pool level of every padded cell, and which cells use it as a flat surface."""
        level = self._pool_level(hp)
        pool = torch.zeros_like(hp, dtype=torch.bool)
        if self.shoreline == "kp07":
            return level, pool
        partial = (hp > 0) & (hp < self.v_break[2])
        surface = torch.where(partial, level, wp)
        wet = hp > 0
        centre = surface[1:-1, 1:-1]
        gap = torch.zeros_like(centre)
        for rows, cols in ((slice(None, -2), slice(1, -1)), (slice(2, None), slice(1, -1)),
                           (slice(1, -1), slice(None, -2)), (slice(1, -1), slice(2, None))):
            gap = torch.maximum(gap, torch.where(wet[rows, cols], (surface[rows, cols] - centre).abs(), 0.0))
        pool[1:-1, 1:-1] = partial[1:-1, 1:-1] & (gap <= POOL_TOLERANCE * self.relief[1:-1, 1:-1])
        return level, pool

    def _settle(self, s: State, w, hu, hv):
        # Rounding can leave a depth a hair below zero; lift it to zero and record how much water that added
        s.clamped = s.clamped + torch.clamp(self.bc - w, min=0).double().sum()
        w = torch.maximum(w, self.bc)
        dry = w <= self.bc
        return w, torch.where(dry, torch.zeros_like(hu), hu), torch.where(dry, torch.zeros_like(hv), hv)

    def step(self, s: State, t_stop: float = math.inf) -> float:
        """One second-order Runge-Kutta (SSP) step, never past t_stop. Returns the time step used."""
        dw, dhu, dhv, speeds = self._rates(s.w, s.hu, s.hv)
        ax, ay = speeds.tolist()
        limits = [d / a for d, a in ((self.dx, ax), (self.dy, ay)) if a > 0]
        dt = min(self.cfl * min(limits) if limits else math.inf, t_stop - s.t)
        if not math.isfinite(dt):
            raise ValueError("no water is moving and no stop time was given")
        w1, hu1, hv1 = self._settle(s, s.w + dt * dw, s.hu + dt * dhu, s.hv + dt * dhv)
        dw, dhu, dhv, _ = self._rates(w1, hu1, hv1)
        s.w, s.hu, s.hv = self._settle(s, 0.5 * (s.w + w1 + dt * dw), 0.5 * (s.hu + hu1 + dt * dhu),
                                       0.5 * (s.hv + hv1 + dt * dhv))
        s.t += dt
        s.steps += 1
        return dt

    def run(self, s: State, t_end: float) -> State:
        """Advance s to exactly t_end seconds."""
        while t_end - s.t > 1e-9 * max(1.0, t_end):
            self.step(s, t_end)
        return s
