"""P1 step 5: a U-Net that maps glacial lakes from one Sentinel-2 scene plus slope.

Inputs, per 10 m cell (`features`): the six Level-1C bands B2, B3, B4, B8, B11, B12 as reflectance,
whether the ground is steeper than 12 degrees, and two water indices (NDWI from B3/B8, MNDWI from
B3/B11), standardised with the training set's mean and spread. Output: the probability that the
cell is lake water.

Terrain enters only as the baseline rule's own 12-degree mask, never as slope itself: GLO-30 levels
lake surfaces flat (from radar of about 2011-2015), so in the training tiles ground under 1 degree
covers half of all lake cells and 0.5% of the rest. A model given slope learns those old outlines
instead of reading the scene, which defeats growth curves.

The same code trains on a laptop CPU or a Colab GPU; nothing here touches Earth Engine.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from . import tiles

BANDS = ("B2", "B3", "B4", "B8", "B11", "B12")
CHANNELS = BANDS + ("steep", "ndwi", "mndwi")
RAW = BANDS + ("slope_x100",)  # what the packed training array stores, as uint16


# --- Features ---------------------------------------------------------------------------------------

def features(raw: np.ndarray) -> np.ndarray:
    """(..., 7, H, W) uint16 [B2, B3, B4, B8, B11, B12, slope x 100] -> (..., 9, H, W) float32, unscaled."""
    raw = raw.astype(np.float32)
    bands = np.clip(raw[..., :6, :, :] / 10000.0, 0, 2)
    steep = (raw[..., 6:7, :, :] >= tiles.MAX_SLOPE_DEG * 100).astype(np.float32)
    b3, b8, b11 = bands[..., 1:2, :, :], bands[..., 3:4, :, :], bands[..., 4:5, :, :]
    ndwi = (b3 - b8) / np.maximum(b3 + b8, 1e-4)
    mndwi = (b3 - b11) / np.maximum(b3 + b11, 1e-4)
    return np.concatenate([bands, steep, ndwi, mndwi], axis=-3)


def raw_from_tile(tile: dict) -> np.ndarray:
    """A step 4 hard-case tile (moraine/tiles.py) as the (7, H, W) uint16 array `features` expects."""
    slope_x100 = np.round(tile["slope"].astype(np.float64) * 100).astype(np.uint16)
    return np.stack([tile[b].astype(np.uint16) for b in BANDS] + [slope_x100])


# --- Model ------------------------------------------------------------------------------------------

def _block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
                         nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))


class UNet(nn.Module):
    """A plain U-Net: `depth` halvings, `base` channels at full resolution, doubling at each level.
    Takes any input whose sides divide by 2**depth."""

    def __init__(self, cin: int = len(CHANNELS), base: int = 24, depth: int = 4):
        super().__init__()
        width = [base * 2 ** i for i in range(depth + 1)]
        self.down = nn.ModuleList([_block(cin, width[0])] + [_block(width[i], width[i + 1]) for i in range(depth)])
        self.up = nn.ModuleList([nn.ConvTranspose2d(width[i + 1], width[i], 2, stride=2) for i in reversed(range(depth))])
        self.merge = nn.ModuleList([_block(width[i] * 2, width[i]) for i in reversed(range(depth))])
        self.head = nn.Conv2d(width[0], 1, 1)
        self.register_buffer("mean", torch.zeros(cin))
        self.register_buffer("std", torch.ones(cin))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Unscaled features (N, C, H, W) -> lake logits (N, 1, H, W)."""
        x = (x - self.mean[None, :, None, None]) / self.std[None, :, None, None]
        skips = []
        for level, block in enumerate(self.down):
            x = block(x if level == 0 else F.max_pool2d(x, 2))
            skips.append(x)
        x = skips.pop()
        for up, merge in zip(self.up, self.merge):
            x = merge(torch.cat([up(x), skips.pop()], 1))
        return self.head(x)


def loss_fn(logits: torch.Tensor, label: torch.Tensor) -> torch.Tensor:
    """Cross-entropy plus soft Dice, so the few lake cells in a tile count as much as the many others."""
    bce = F.binary_cross_entropy_with_logits(logits, label)
    p = torch.sigmoid(logits)
    dice = 1 - (2 * (p * label).sum() + 1) / (p.sum() + label.sum() + 1)
    return bce + dice


# --- Training data ----------------------------------------------------------------------------------

class TileSet(torch.utils.data.Dataset):
    """Random `crop` x `crop` windows of the packed training tiles, in one of the 8 flips and rotations."""

    def __init__(self, raw: np.ndarray, labels: np.ndarray, crop: int, seed: int = 0):
        self.raw, self.labels, self.crop = raw, labels, crop
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.raw)

    def __getitem__(self, i: int):
        size = self.raw.shape[-1]
        r, c = self.rng.integers(0, size - self.crop + 1, 2)
        x = features(np.asarray(self.raw[i, :, r:r + self.crop, c:c + self.crop]))
        y = np.asarray(self.labels[i, r:r + self.crop, c:c + self.crop], dtype=np.float32)[None]
        k = int(self.rng.integers(4))
        x, y = np.rot90(x, k, axes=(1, 2)), np.rot90(y, k, axes=(1, 2))
        if self.rng.integers(2):
            x, y = x[:, :, ::-1], y[:, :, ::-1]
        return torch.from_numpy(x.copy()), torch.from_numpy(y.copy())


def channel_stats(raw: np.ndarray, sample: int = 400, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Mean and spread of each feature channel over a sample of training tiles."""
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(raw), size=min(sample, len(raw)), replace=False))
    f = features(np.asarray(raw[pick]))
    return f.mean(axis=(0, 2, 3)), f.std(axis=(0, 2, 3)) + 1e-6


# --- Use --------------------------------------------------------------------------------------------

@torch.no_grad()
def predict(model: UNet, raw: np.ndarray, device: str = "cpu") -> np.ndarray:
    """Lake probability for one (7, H, W) raw tile; H and W are padded up to a multiple of 16."""
    model.eval()
    h, w = raw.shape[-2:]
    ph, pw = -h % 16, -w % 16
    x = np.pad(features(raw), ((0, 0), (0, ph), (0, pw)), mode="reflect")
    p = torch.sigmoid(model(torch.from_numpy(x)[None].to(device)))[0, 0, :h, :w]
    return p.cpu().numpy()


def lake_mask(probability: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    """Lake cells, in patches of at least 0.02 km2 as for the baseline rule."""
    return tiles.drop_small(probability > threshold)


def save(model: UNet, path, **info) -> None:
    torch.save({"state": model.state_dict(), "base": model.merge[-1][0].out_channels, "depth": len(model.up), **info},
               path)


def load(path, device: str = "cpu") -> tuple[UNet, dict]:
    saved = torch.load(path, map_location=device, weights_only=False)
    model = UNet(base=saved["base"], depth=saved["depth"]).to(device)
    model.load_state_dict(saved["state"])
    model.eval()
    return model, {k: v for k, v in saved.items() if k != "state"}
