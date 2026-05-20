import os
import requests
from dotenv import load_dotenv

load_dotenv()

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

token = get_token()

r = requests.get(
    "https://catalogue.dataspace.copernicus.eu/odata/v1/Products",
    params={
        "$filter": (
            "Collection/Name eq 'SENTINEL-1' "
            "and ContentDate/Start gt 2020-01-01T00:00:00.000Z "
            "and ContentDate/Start lt 2020-02-01T23:59:59.000Z "
            "and OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((13.093 0.921,13.256 0.921,13.256 1.178,13.093 1.178,13.093 0.921))')"
        ),
        "$top": 10,
        "$expand": "Attributes",
    },
    headers={"Authorization": f"Bearer {token}"}
)
scenes = r.json().get("value", [])
print(f"Found {len(scenes)} scenes")
for s in scenes:
    orbit = next((a['Value'] for a in s.get('Attributes', []) if a['Name'] == 'orbitDirection'), 'unknown')
    print(f"  {s['Name']} -- {orbit}")