from pyproj import Transformer

t = Transformer.from_crs("EPSG:32633", "EPSG:4326", always_xy=True)

corners = {
    "top_left": (287750.7524, 130291.7840),
    "bottom_right": (305915.5414, 101894.9163),
}

for name, (x, y) in corners.items():
    lon, lat = t.transform(x, y)
    print(f"{name}: {lon:.6f}, {lat:.6f}")