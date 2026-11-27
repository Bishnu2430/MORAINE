"""P1 step 5: pack what the Colab notebook needs into pipeline/data/p1_unet_bundle.zip.

    .venv\\Scripts\\python pipeline\\scripts\\p1_unet_bundle.py

The zip mirrors the repository's layout, so pipeline/scripts/p1_unet.py runs unchanged inside it:
the packed training arrays, the validation hard-case tiles (never the North Sikkim test tiles), the
case list, and the code (moraine/tiles.py, moraine/unet.py, the training script). Run p1_unet.py
once first (even with --epochs 0) so the training arrays exist.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"


def main() -> int:
    data = PIPELINE / "data" / "p1_unet"
    needed = [data / name for name in ("train_raw.npy", "train_labels.npy", "train_keys.json", "index.json")]
    missing = [p.name for p in needed if not p.exists()]
    if missing:
        sys.exit(f"Missing {missing}: run pipeline/scripts/p1_unet.py --epochs 0 first to pack the tiles.")
    cases = json.loads((ROOT / "docs" / "p1" / "hard-cases.json").read_text())
    validation = [PIPELINE / "data" / "p1_hard_cases" / f"{c['case']}.npz" for c in cases if c["split"] == "validation"]
    code = [PIPELINE / "moraine" / name for name in ("__init__.py", "tiles.py", "unet.py")]
    code += [PIPELINE / "scripts" / "p1_unet.py", ROOT / "docs" / "p1" / "hard-cases.json"]
    out = PIPELINE / "data" / "p1_unet_bundle.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in needed + validation + code:
            z.write(path, path.relative_to(ROOT).as_posix())
    print(f"{out}: {out.stat().st_size / 1e6:.0f} MB, {len(validation)} validation tiles, no test tiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
