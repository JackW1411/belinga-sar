import numpy as np
from scipy.ndimage import uniform_filter


def to_db(arr):
    """Raw GRD amplitude DN to dB. Power = amplitude squared."""
    arr = arr.astype(np.float32)
    arr[arr == 0] = np.nan
    return 10 * np.log10(arr ** 2 + 1e-10)


def lee_filter(arr, size=7):
    arr = arr.copy()
    nan_mask = ~np.isfinite(arr)
    arr[nan_mask] = 0
    mean     = uniform_filter(arr, size)
    mean_sq  = uniform_filter(arr ** 2, size)
    variance = mean_sq - mean ** 2
    overall_var = np.var(arr[arr != 0])
    weights  = variance / (variance + overall_var)
    filtered = mean + weights * (arr - mean)
    filtered[nan_mask] = np.nan
    return filtered


def load_band(path):
    import rasterio
    with rasterio.open(path) as src:
        return src.read(1).astype(np.float32), src.meta.copy()


def prepare_scene(vv_path, vh_path):
    """Load and convert to linear power. Returns (vv_linear, vh_linear)."""
    vv_raw, _ = load_band(vv_path)
    vh_raw, _ = load_band(vh_path)
    vv_raw[vv_raw == 0] = np.nan
    vh_raw[vh_raw == 0] = np.nan
    vv_linear = lee_filter(vv_raw.astype(np.float32) ** 2)
    vh_linear = lee_filter(vh_raw.astype(np.float32) ** 2)
    return vv_linear, vh_linear