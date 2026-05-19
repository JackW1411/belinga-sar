import os
import requests
import zipfile
from dotenv import load_dotenv

load_dotenv()

AOI_WKT = "POLYGON((13.093 0.921,13.256 0.921,13.256 1.178,13.093 1.178,13.093 0.921))"

BASELINE_START = "2019-01-01"
BASELINE_END   = "2021-01-01"
POST_START     = "2021-01-01"
POST_END       = "2026-06-01"


def get_token():
    r = requests.post(
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "username": os.getenv("CDSE_USER"),
            "password": os.getenv("CDSE_PASSWORD"),
            "client_id": "cdse-public",
        }
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search_scenes(start, end, token):
    filter_str = (
        f"Collection/Name eq 'SENTINEL-1' "
        f"and ContentDate/Start gt {start}T00:00:00.000Z "
        f"and ContentDate/Start lt {end}T23:59:59.000Z "
        f"and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'GRD') "
        f"and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'operationalMode' and att/OData.CSC.StringAttribute/Value eq 'IW') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{AOI_WKT}')"
    )
    r = requests.get(
        "https://catalogue.dataspace.copernicus.eu/odata/v1/Products",
        params={
            "$filter": filter_str,
            "$top": 200,
            "$orderby": "ContentDate/Start asc",
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    r.raise_for_status()
    scenes = r.json().get("value", [])
    print(f"  Found {len(scenes)} scenes ({start} to {end})")
    return scenes


def download_and_extract(scene, token, out_dir="downloads"):
    os.makedirs(out_dir, exist_ok=True)
    name = scene["Name"]
    safe_path = os.path.join(out_dir, f"{name}.SAFE")

    # Skip if already extracted
    if os.path.exists(safe_path):
        print(f"  Already extracted: {name}")
        return safe_path

    zip_path = os.path.join(out_dir, f"{name}.zip")

    # Download if zip not present
    if not os.path.exists(zip_path):
        product_id = scene["Id"]
        url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            stream=True,
            allow_redirects=True
        )
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  {name}: {pct:.1f}% ({downloaded/1e6:.0f}/{total/1e6:.0f} MB)", end="", flush=True)
        print()

    # Extract and delete zip
    print(f"  Extracting {name}...")
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(out_dir)
    os.remove(zip_path)
    print(f"  Extracted, zip deleted")

    return safe_path


def get_all_scenes(token):
    print("Searching baseline scenes (2019-2021)...")
    baseline = search_scenes(BASELINE_START, BASELINE_END, token)
    print("Searching post-disturbance scenes (2021-2026)...")
    post = search_scenes(POST_START, POST_END, token)
    return baseline, post