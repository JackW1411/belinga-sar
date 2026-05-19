import xml.etree.ElementTree as ET
import numpy as np
import rasterio
import tempfile
import os
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.control import GroundControlPoint
from pathlib import Path

AOI_LON = (13.093, 13.256)
AOI_LAT = (0.921, 1.178)
OUTPUT_RES = 0.0001  # ~10m in degrees


def parse_gcps(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    gcps = []
    for gcp in root.findall('.//geolocationGridPoint'):
        line  = float(gcp.find('line').text)
        pixel = float(gcp.find('pixel').text)
        lat   = float(gcp.find('latitude').text)
        lon   = float(gcp.find('longitude').text)
        gcps.append(GroundControlPoint(row=line, col=pixel, x=lon, y=lat))
    return gcps


def find_safe_files(safe_path, polarisation):
    """Find tiff and xml for a given polarisation (vv or vh) inside a .SAFE dir."""
    safe = Path(safe_path)
    pol = polarisation.lower()

    tiffs = list((safe / "measurement").glob(f"*-{pol}-*.tiff"))
    xmls  = list((safe / "annotation").glob(f"*-{pol}-*.xml"))

    if not tiffs or not xmls:
        raise FileNotFoundError(f"Could not find {pol} files in {safe_path}")

    return str(tiffs[0]), str(xmls[0])


def georeference_band(tiff_path, xml_path, out_path):
    wgs84 = CRS.from_epsg(4326)
    gcps  = parse_gcps(xml_path)

    with rasterio.open(tiff_path) as src:
        raw = src.read(1).astype(np.float32)
        h, w = raw.shape

    # Write raw data to temp file with GCPs attached
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_path = tmp.name

    with rasterio.open(tmp_path, "w", driver="GTiff", dtype="float32",
                       width=w, height=h, count=1, crs=wgs84) as tmp_ds:
        tmp_ds.write(raw, 1)
        tmp_ds.gcps = (gcps, wgs84)

    # Reproject to regular grid using all GCPs
    lon_min, lon_max = AOI_LON
    lat_min, lat_max = AOI_LAT
    dst_w = int((lon_max - lon_min) / OUTPUT_RES)
    dst_h = int((lat_max - lat_min) / OUTPUT_RES)
    dst_transform = from_bounds(lon_min, lat_min, lon_max, lat_max, dst_w, dst_h)
    dst = np.zeros((dst_h, dst_w), dtype=np.float32)

    with rasterio.open(tmp_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_crs=wgs84,
            gcps=src.gcps[0],
            dst_transform=dst_transform,
            dst_crs=wgs84,
            resampling=Resampling.bilinear,
        )

    os.unlink(tmp_path)
    dst[dst == 0] = np.nan

    with rasterio.open(out_path, "w", driver="GTiff", dtype="float32",
                       width=dst_w, height=dst_h, count=1,
                       crs=wgs84, transform=dst_transform,
                       nodata=float("nan")) as f:
        f.write(dst, 1)

    print(f"  Saved {out_path} | shape: {dst.shape} | valid px: {np.sum(np.isfinite(dst)):,}")


def process_safe(safe_path, date_str, out_dir="georef"):
    """Georeference VV and VH from a .SAFE directory. Returns (vv_path, vh_path)."""
    os.makedirs(out_dir, exist_ok=True)
    vv_out = os.path.join(out_dir, f"vv_{date_str}.tif")
    vh_out = os.path.join(out_dir, f"vh_{date_str}.tif")

    if os.path.exists(vv_out) and os.path.exists(vh_out):
        print(f"  Already georeferenced: {date_str}")
        return vv_out, vh_out

    print(f"Georeferencing {date_str}...")
    vv_tiff, vv_xml = find_safe_files(safe_path, "vv")
    vh_tiff, vh_xml = find_safe_files(safe_path, "vh")

    georeference_band(vv_tiff, vv_xml, vv_out)
    georeference_band(vh_tiff, vh_xml, vh_out)

    return vv_out, vh_out