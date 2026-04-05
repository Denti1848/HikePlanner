import datetime
import json
import math
import os
import pickle
import shutil
import requests
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
from azure.storage.blob import BlobServiceClient
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

ENV_STORAGE_KEY = "AZURE_STORAGE_CONNECTION_STRING"
MODEL_CONTAINER_PREFIX = "hikeplanner-model"

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path, override=True)
print("*** Load Model from Blob Storage ***")
if ENV_STORAGE_KEY in os.environ:
    azureStorageConnectionString = os.environ[ENV_STORAGE_KEY]
    blob_service_client = BlobServiceClient.from_connection_string(azureStorageConnectionString)
    containers = blob_service_client.list_containers(include_metadata=True)
    suffix = max(
        int(container.name.split("-")[-1])
        for container in containers
        if container.name.startswith(MODEL_CONTAINER_PREFIX)
    )
    model_folder = f"{MODEL_CONTAINER_PREFIX}-{suffix}"
    print(f"using version {model_folder}")
    container_client = blob_service_client.get_container_client(model_folder)
    blob_list = list(container_client.list_blobs())
    local_model_dir = Path("./model")
    if local_model_dir.exists():
        shutil.rmtree(local_model_dir)
    local_model_dir.mkdir(parents=True, exist_ok=True)
    for blob in blob_list:
        download_file_path = local_model_dir / blob.name
        print(f"downloading blob to {download_file_path.resolve()}")
        with open(file=download_file_path, mode="wb") as download_file:
            download_file.write(container_client.download_blob(blob.name).readall())
else:
    print("CANNOT ACCESS AZURE BLOB STORAGE")
    print(os.environ)

gbr_model_path = Path(".", "model", "GradientBoostingRegressor.pkl")
with open(gbr_model_path, 'rb') as fid:
    gradient_model = pickle.load(fid)

linear_model_path = Path(".", "model", "LinearRegression.pkl")
with open(linear_model_path, 'rb') as fid:
    linear_model = pickle.load(fid)


# ─── Hilfsfunktionen Gehzeit ────────────────────────────────────────────────

def din33466(uphill, downhill, distance):
    km = distance / 1000.0
    vertical = downhill / 500.0 + uphill / 300.0
    horizontal = km / 4.0
    return 3600.0 * (min(vertical, horizontal) / 2 + max(vertical, horizontal))


def sac(uphill, downhill, distance):
    km = distance / 1000.0
    return 3600.0 * (uphill / 400.0 + km / 4.0)


def timedelta_minutes(seconds):
    rounded_minutes = int(round(seconds / 60.0))
    return str(datetime.timedelta(minutes=rounded_minutes))


# ─── Koordinaten-Konvertierung WGS84 ↔ LV95 ────────────────────────────────

def wgs84_to_lv95(lat, lng):
    """WGS84 (lat/lng) → SwissTopo LV95 (E, N)"""
    lat_aux = (lat * 3600 - 169028.66) / 10000
    lng_aux = (lng * 3600 - 26782.5) / 10000
    e = (2600072.37
         + 211455.93 * lng_aux
         - 10938.51  * lng_aux * lat_aux
         - 0.36      * lng_aux * lat_aux ** 2
         - 44.54     * lng_aux ** 3)
    n = (1200147.07
         + 308807.95 * lat_aux
         + 3745.25   * lng_aux ** 2
         + 76.63     * lat_aux ** 2
         - 194.56    * lng_aux ** 2 * lat_aux
         + 119.79    * lat_aux ** 3)
    return e, n


# ─── SwissTopo API-Funktionen ────────────────────────────────────────────────

def get_trail_geometry_lv95(lat, lng):

    e, n = wgs84_to_lv95(lat, lng)
    radius = 500  # 500m Suchradius

    url = "https://api3.geo.admin.ch/rest/services/ech/MapServer/identify"
    params = {
        "geometry":       f"{e},{n}",
        "geometryType":   "esriGeometryPoint",
        "layers":         "all:ch.swisstopo.swisstlm3d-wanderwege",
        "mapExtent":      f"{e-radius},{n-radius},{e+radius},{n+radius}",
        "imageDisplay":   "1000,1000,96",
        "tolerance":      "50",
        "returnGeometry": "true",
        "geometryFormat": "geojson",
        "sr":             "2056",
        "limit":          "1",
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        return None

    feature   = results[0]
    geometry  = feature.get("geometry", {})
    geom_type = geometry.get("type", "")

    if geom_type == "LineString":
        coords = geometry.get("coordinates", [])
    elif geom_type == "MultiLineString":
        parts  = geometry.get("coordinates", [[]])
        coords = max(parts, key=len)
    else:
        return None

    if len(coords) < 2:
        return None

    return {
        "attrs":       feature.get("properties", {}),
        "coords_lv95": coords
    }


def get_elevation_profile(coords_lv95):
    if not coords_lv95 or len(coords_lv95) < 2:
        return None

    # Koordinaten auf max. 100 Punkte reduzieren (API-Limit + Performance)
    if len(coords_lv95) > 100:
        step = len(coords_lv95) // 100
        coords_lv95 = coords_lv95[::step]

    geom_json = json.dumps({
        "type": "LineString",
        "coordinates": coords_lv95
    })

    url = "https://api3.geo.admin.ch/rest/services/profile.json"

    # POST mit form-data (URI-Längen fix) 
    resp = requests.post(
        url,
        data={
            "geom":      geom_json,
            "sr":        "2056",
            "nb_points": "200",
        },
        timeout=15
    )
    resp.raise_for_status()
    profile = resp.json()

    if not profile or len(profile) < 2:
        return None

    uphill   = 0.0
    downhill = 0.0

    for i in range(1, len(profile)):
        dh = profile[i]["alts"]["COMB"] - profile[i - 1]["alts"]["COMB"]
        if dh > 0:
            uphill   += dh
        else:
            downhill += abs(dh)

    total_dist = profile[-1]["dist"]

    return {
        "length_m": total_dist,
        "uphill":   round(uphill),
        "downhill": round(downhill),
    }


# ─── Flask App ───────────────────────────────────────────────────────────────

print("\n*** Flask Backend ***")
app = Flask(__name__)
CORS(app)
app = Flask(__name__, static_folder='/usr/src/app/frontend/build')
app.static_url_path = '/'


@app.route("/")
def indexPage():
    return send_file("../frontend/build/index.html")


@app.route("/<path:path>")
def catch_all(path):
    if path.startswith("api/"):
        return "API Route", 404
    try:
        return send_file(f"../frontend/build/{path}")
    except FileNotFoundError:
        return send_file("../frontend/build/index.html")


@app.route("/api/hiking")
def get_hiking_route():
    """Map-Klick → SwissTopo Identify + Elevation Profile"""
    lat = float(request.args.get('lat', 46.8))
    lng = float(request.args.get('lng',  8.2))

    try:
        # 1. Trail-Geometrie in LV95 holen
        trail = get_trail_geometry_lv95(lat, lng)
        if not trail:
            return jsonify({"error": "Kein Wanderweg in der Nähe gefunden"}), 404

        # 2. Höhenprofil – LV95-Koordinaten direkt übergeben
        profile = get_elevation_profile(trail["coords_lv95"])
        if not profile:
            return jsonify({"error": "Höhenprofil konnte nicht berechnet werden"}), 500

        length_m = profile["length_m"]
        uphill   = profile["uphill"]
        downhill = profile["downhill"]
        length_km = round(length_m / 1000, 2)

        # 3. ML-Predictions
        demodf = pd.DataFrame(
            columns=['downhill', 'uphill', 'length_3d', 'max_elevation'],
            data=[[downhill, uphill, length_m, 0]]
        )
        gradient_prediction = gradient_model.predict(demodf)[0]
        linear_prediction   = linear_model.predict(demodf)[0]

        return jsonify({
            "length":   length_km,
            "uphill":   uphill,
            "downhill": downhill,
            "time":     timedelta_minutes(gradient_prediction),
            "linear":   timedelta_minutes(linear_prediction),
            "din33466": timedelta_minutes(din33466(uphill=uphill, downhill=downhill, distance=length_m)),
            "sac":      timedelta_minutes(sac(uphill=uphill, downhill=downhill, distance=length_m)),
        })

    except requests.exceptions.HTTPError as e:
        print(f"SwissTopo HTTP-Fehler: {e} | Response: {e.response.text[:300]}")
        return jsonify({"error": f"SwissTopo API Fehler: {e.response.status_code}"}), 502
    except requests.exceptions.RequestException as e:
        print(f"SwissTopo Verbindungsfehler: {e}")
        return jsonify({"error": f"SwissTopo API nicht erreichbar: {str(e)}"}), 503


@app.route("/api/predict")
def predict():
    downhill = request.args.get('downhill', default=0, type=int)
    uphill   = request.args.get('uphill',   default=0, type=int)
    length   = request.args.get('length',   default=0, type=int)

    demodf = pd.DataFrame(
        columns=['downhill', 'uphill', 'length_3d', 'max_elevation'],
        data=[[downhill, uphill, length, 0]]
    )
    gradient_prediction = gradient_model.predict(demodf)[0]
    linear_prediction   = linear_model.predict(demodf)[0]

    return jsonify({
        'time':     timedelta_minutes(gradient_prediction),
        'linear':   timedelta_minutes(linear_prediction),
        'din33466': timedelta_minutes(din33466(uphill=uphill, downhill=downhill, distance=length)),
        'sac':      timedelta_minutes(sac(uphill=uphill, downhill=downhill, distance=length)),
    })