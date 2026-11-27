import numpy as np
import torch

from moraine import unet


def raw_tile(size=32, lake=None):
    """A synthetic (7, size, size) raw tile: dry ground, plus water where `lake` is True."""
    lake = np.zeros((size, size), dtype=bool) if lake is None else lake
    def band(water, ground):
        return np.where(lake, water, ground).astype(np.uint16)
    return np.stack([band(900, 1500), band(900, 1600), band(500, 1800), band(300, 2500), band(100, 2600),
                     band(80, 2200), np.full((size, size), 300, dtype=np.uint16)])


def test_features_have_the_water_indices_and_only_the_baselines_slope_mask():
    lake = np.zeros((32, 32), dtype=bool)
    lake[8:24, 8:24] = True
    raw = raw_tile(lake=lake)
    raw[6, :, 16:] = 1500  # 15 degrees on the right half, 3 degrees on the left
    f = unet.features(raw)
    assert f.shape == (len(unet.CHANNELS), 32, 32)
    ndwi, mndwi = f[unet.CHANNELS.index("ndwi")], f[unet.CHANNELS.index("mndwi")]
    assert abs(ndwi[10, 10] - 0.5) < 1e-6 and ndwi[0, 0] < 0 and mndwi[10, 10] > 0.7
    steep = f[unet.CHANNELS.index("steep")]
    assert (steep[:, :16] == 0).all() and (steep[:, 16:] == 1).all()  # no finer slope than the 12-degree mask


def test_tileset_keeps_image_and_label_aligned_through_crops_and_flips():
    lake = np.zeros((48, 48), dtype=bool)
    lake[5:20, 30:44] = True
    raw, labels = raw_tile(48, lake)[None], lake.astype(np.uint8)[None]
    data = unet.TileSet(raw, labels, crop=32, seed=1)
    for _ in range(20):
        x, y = data[0]
        water = x[unet.CHANNELS.index("ndwi")] > 0
        assert torch.equal(water, y[0] > 0.5)


def test_unet_predicts_any_size_and_round_trips_through_a_checkpoint(tmp_path):
    model = unet.UNet(base=4, depth=2)
    p = unet.predict(model, raw_tile(36))  # padded to 48 inside, cropped back
    assert p.shape == (36, 36) and (p >= 0).all() and (p <= 1).all()
    unet.save(model, tmp_path / "m.pt", epoch=3)
    again, info = unet.load(tmp_path / "m.pt")
    assert info["epoch"] == 3 and info["base"] == 4 and np.allclose(unet.predict(again, raw_tile(36)), p, atol=1e-6)


def test_a_tiny_unet_learns_a_lake():
    torch.manual_seed(0)
    lake = np.zeros((32, 32), dtype=bool)
    lake[6:26, 10:22] = True
    raw, labels = raw_tile(32, lake)[None].repeat(8, 0), lake.astype(np.uint8)[None].repeat(8, 0)
    model = unet.UNet(base=4, depth=2)
    mean, std = unet.channel_stats(raw)
    model.mean.copy_(torch.from_numpy(mean))
    model.std.copy_(torch.from_numpy(std))
    loader = torch.utils.data.DataLoader(unet.TileSet(raw, labels, crop=32), batch_size=8)
    optimiser = torch.optim.Adam(model.parameters(), lr=0.02)
    for _ in range(40):
        for x, y in loader:
            model.train()
            loss = unet.loss_fn(model(x), y)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
    predicted = unet.predict(model, raw[0]) > 0.5
    assert (predicted == lake).mean() > 0.97
