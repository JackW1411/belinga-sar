import os
os.environ["PROJ_DATA"] = r".venv\Lib\site-packages\rasterio\proj_data"
os.environ["PROJ_LIB"] = r".venv\Lib\site-packages\rasterio\proj_data"
import json
from pathlib import Path
from datetime import datetime

from pipeline     import get_token, get_all_scenes, download_and_extract
from georeference import process_safe
from process      import prepare_scene
from time_series  import init_stacks, write_scene, compute_rcr, DATES_FILE, H, W

import numpy as np
import rasterio


OUTPUT_DIR   = "outputs"
GEOREF_DIR   = "georef"
DOWNLOAD_DIR = "downloads"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def scene_date(scene):
    return scene["ContentDate"]["Start"][:10].replace("-", "")


def save_output(arr, transform, crs, path, dtype="float32"):
    h, w = arr.shape
    with rasterio.open(path, "w", driver="GTiff", dtype=dtype,
                       width=w, height=h, count=1,
                       crs=crs, transform=transform,
                       nodata=float("nan")) as dst:
        dst.write(arr.astype(dtype), 1)
    print(f"Saved: {path}")


def main():
    print("=== Belinga SAR Change Detection ===\n")

    print("Authenticating with CDSE...")
    token = get_token()
    print("OK\n")

    baseline_scenes, post_scenes = get_all_scenes(token)
    all_scenes = baseline_scenes + post_scenes
    n = len(all_scenes)
    print(f"\nTotal scenes: {n} ({len(baseline_scenes)} baseline, {len(post_scenes)} post)\n")

    if n == 0:
        print("No scenes found. Check AOI and date range.")
        return

    vv_stack, vh_stack = init_stacks(n)
    dates = []
    ref_meta = None

    for i, scene in enumerate(all_scenes):
        date = scene_date(scene)
        print(f"\n[{i+1}/{n}] {date}")

        # 1. Download and extract .SAFE
        safe_path = download_and_extract(scene, token, DOWNLOAD_DIR)

        # 2. Georeference VV + VH
        vv_path, vh_path = process_safe(safe_path, date, GEOREF_DIR)

        # 3. Load reference metadata from first scene
        if ref_meta is None:
            with rasterio.open(vv_path) as src:
                ref_meta = src.meta.copy()

        # 4. Convert to dB, apply Lee filter
        vv_db, vh_db = prepare_scene(vv_path, vh_path)

        # 5. Write to memmap stack
        write_scene(vv_stack, vh_stack, i, vv_db, vh_db)
        dates.append(scene["ContentDate"]["Start"][:10])

        # 6. Delete intermediates to save disk
        Path(vv_path).unlink(missing_ok=True)
        Path(vh_path).unlink(missing_ok=True)
        # Delete .SAFE dir
        import shutil
        shutil.rmtree(safe_path, ignore_errors=True)
        print(f"  Cleaned up {date}")

    # Save dates index
    with open(DATES_FILE, "w") as f:
        json.dump(dates, f, indent=2)
    print(f"\nDates saved to {DATES_FILE}")

    # 7. Compute RCR disturbance map
    print("\nComputing disturbance map...")
    disturbance, baseline_vv, loss_count = compute_rcr(vv_stack, vh_stack, dates)

    print(f"  Disturbed pixels: {np.sum(disturbance):,}")
    print(f"  Disturbed area:   {np.sum(disturbance) * 0.01:.1f} ha (approx at 10m)")

    # 8. Save outputs
    t = ref_meta["transform"]
    crs = ref_meta["crs"]

    save_output(disturbance.astype(np.float32), t, crs,
                f"{OUTPUT_DIR}/disturbance.tif")
    save_output(loss_count.astype(np.float32), t, crs,
                f"{OUTPUT_DIR}/loss_count.tif")
    save_output(baseline_vv, t, crs,
                f"{OUTPUT_DIR}/baseline_vv.tif")

    print("\nDone. Load outputs/disturbance.tif in QGIS to review.")


if __name__ == "__main__":
    main()