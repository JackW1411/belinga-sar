import os
os.environ["PROJ_DATA"] = r".venv\Lib\site-packages\rasterio\proj_data"
os.environ["PROJ_LIB"]  = r".venv\Lib\site-packages\rasterio\proj_data"

import shutil
from pathlib import Path

import numpy as np
import rasterio

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from rasterio.plot import show


from pipeline     import get_token, search_scenes, download_and_extract
from georeference import process_safe
from process      import prepare_scene

# --- Config ---
BASELINE_DATE = ("2020-01-01", "2020-02-01")
POST_DATE     = ("2026-01-01", "2026-02-01")
DOWNLOAD_DIR  = "downloads"
GEOREF_DIR    = "georef"
OUTPUT_DIR    = "outputs"


def pick_scene(scenes, label):
    if not scenes:
        raise RuntimeError(f"No scenes found for {label}")
    print(f"  {label}: using {scenes[0]['Name']}")
    return scenes[0]


def save_tif(arr, meta, path):
    with rasterio.open(path, "w", driver="GTiff", dtype="float32",
                       width=meta["width"], height=meta["height"], count=1,
                       crs=meta["crs"], transform=meta["transform"],
                       nodata=float("nan")) as dst:
        dst.write(arr.astype(np.float32), 1)
    print(f"  Saved: {path}")


def get_georef(safe_path, date_str, georef_dir):
    """Return georef paths, reusing cached tifs if .SAFE is gone."""
    vv = os.path.join(georef_dir, f"vv_{date_str}.tif")
    vh = os.path.join(georef_dir, f"vh_{date_str}.tif")
    if os.path.exists(vv) and os.path.exists(vh):
        print(f"  Already georeferenced: {date_str}")
        return vv, vh
    return process_safe(safe_path, date_str, georef_dir)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Authenticating...")
    token = get_token()

    print("Searching scenes...")
    baseline_scenes = search_scenes(*BASELINE_DATE, token)
    post_scenes     = search_scenes(*POST_DATE, token)

    baseline = pick_scene(baseline_scenes, "baseline")
    post     = pick_scene(post_scenes,     "post")

    baseline_date = baseline["ContentDate"]["Start"][:10].replace("-", "")
    post_date     = post["ContentDate"]["Start"][:10].replace("-", "")

    # Download (skips if already extracted)
    print("\nDownloading baseline...")
    baseline_safe = download_and_extract(baseline, token, DOWNLOAD_DIR)
    print("Downloading post...")
    post_safe = download_and_extract(post, token, DOWNLOAD_DIR)

    # Georeference (skips if tifs already exist)
    print("\nGeoreferencing...")
    vv_b, vh_b = get_georef(baseline_safe, baseline_date, GEOREF_DIR)
    vv_p, vh_p = get_georef(post_safe,     post_date,     GEOREF_DIR)

    # Load metadata
    with rasterio.open(vv_b) as src:
        meta = src.meta.copy()

    # Convert to dB + Lee filter
    print("\nProcessing...")
    vv_base, vh_base = prepare_scene(vv_b, vh_b)
    vv_post, vh_post = prepare_scene(vv_p, vh_p)

    epsilon = 1e-10
    ratio_base = vv_base / (vh_base + epsilon)
    ratio_post = vv_post / (vh_post + epsilon)
    ratio_diff = 10 * np.log10(ratio_post / (ratio_base + epsilon))  # dB change in ratio

    finite = ratio_diff[np.isfinite(ratio_diff)]
    print(f"\n  ratio_diff stats:")
    print(f"    min:  {finite.min():.4f}")
    print(f"    max:  {finite.max():.4f}")
    print(f"    mean: {finite.mean():.4f}")
    print(f"    std:  {finite.std():.4f}")
    print(f"    >1dB: {(finite > 1.0).sum():,} px")
    print(f"    >3dB: {(finite > 3.0).sum():,} px")

    print("\nSaving outputs...")
    save_tif(10 * np.log10(ratio_base + epsilon), meta, f"{OUTPUT_DIR}/ratio_baseline_{baseline_date}.tif")
    save_tif(10 * np.log10(ratio_post + epsilon), meta, f"{OUTPUT_DIR}/ratio_post_{post_date}.tif")
    save_tif(ratio_diff, meta, f"{OUTPUT_DIR}/ratio_diff_{baseline_date}_vs_{post_date}.tif")

    THRESHOLD = 1.0  # 1 dB increase in VV/VH ratio = likely disturbance
    disturbance = (ratio_diff > THRESHOLD).astype(np.float32)
    disturbance[~np.isfinite(ratio_diff)] = np.nan
    mask_path = f"{OUTPUT_DIR}/disturbance_mask_{baseline_date}_vs_{post_date}.tif"
    save_tif(disturbance, meta, mask_path)

    disturbed_px = int(np.nansum(disturbance))
    disturbed_ha = disturbed_px * 0.01
    print(f"\n  Disturbed pixels : {disturbed_px:,}")
    print(f"  Disturbed area   : {disturbed_ha:.1f} ha (approx at 10m)")

    # PNG map
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))

    def stretch(data):
        finite = data[np.isfinite(data) & (data > 0)]
        p2, p98 = np.percentile(finite, 2), np.percentile(finite, 98)
        return p2, p98

    with rasterio.open(vv_b) as src:
        data = src.read(1).astype(np.float32)
        data[data == 0] = np.nan
        vmin, vmax = stretch(data)
        axes[0].imshow(data, cmap="gray", vmin=vmin, vmax=vmax, aspect="auto")
    axes[0].set_title(f"Sentinel-1 VV Backscatter\nJanuary 2020 (baseline)", fontsize=12)
    axes[0].axis("off")

    with rasterio.open(vv_p) as src:
        data = src.read(1).astype(np.float32)
        data[data == 0] = np.nan
        vmin, vmax = stretch(data)
        axes[1].imshow(data, cmap="gray", vmin=vmin, vmax=vmax, aspect="auto")
    axes[1].set_title(f"Sentinel-1 VV Backscatter\nJanuary 2026 (post)", fontsize=12)
    axes[1].axis("off")

    plt.suptitle("Belinga AOI -- Sentinel-1 SAR\nAutomated scene retrieval and alignment", fontsize=13)
    plt.tight_layout()
    png_path = f"{OUTPUT_DIR}/change_map_{baseline_date}_vs_{post_date}.png"
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Map saved: {png_path}")

    # Cleanup 
    #print("\nCleaning up...")
    #for p in [vv_b, vh_b, vv_p, vh_p]:
     #   Path(p).unlink(missing_ok=True)
    #shutil.rmtree(baseline_safe, ignore_errors=True)
    #shutil.rmtree(post_safe,     ignore_errors=True)

    print("\nDone. Load outputs/disturbance_mask_*.tif in QGIS.")


if __name__ == "__main__":
    main()