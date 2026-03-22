import datetime
import os
import pickle
import shutil
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
from azure.storage.blob import BlobServiceClient
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

ENV_STORAGE_KEY = "AZURE_STORAGE_CONNECTION_STRING"
MODEL_CONTAINER_PREFIX = "hikeplanner-model"

# Lazy loading - Models werden bei erstem Request geladen
gradient_model = None
linear_model = None

# Download-Funktion (wird nur einmal aufgerufen)
def download_models():
    global gradient_model, linear_model
    if gradient_model is not None:
        return  # Schon geladen
    
    print("*** Load Model from Blob Storage ***")
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path, override=True)
    
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

        # Download all blobs to a clean local folder
        local_model_dir = Path("./model")
        if local_model_dir.exists():
            shutil.rmtree(local_model_dir)
        local_model_dir.mkdir(parents=True, exist_ok=True)
        for blob in blob_list:
            download_file_path = local_model_dir / blob.name
            print(f"downloading blob to {download_file_path.resolve()}")
            with open(file=download_file_path, mode="wb") as download_file:
                download_file.write(container_client.download_blob(blob.name).readall())

        gbr_model_path = Path(".", "model", "GradientBoostingRegressor.pkl")
        with open(gbr_model_path, 'rb') as fid:
            gradient_model = pickle.load(fid)

        linear_model_path = Path(".", "model", "LinearRegression.pkl")
        with open(linear_model_path, 'rb') as fid:
            linear_model = pickle.load(fid)
        print("*** Models loaded successfully ***")
    else:
        print("CANNOT ACCESS AZURE BLOB STORAGE - Please set AZURE_STORAGE_CONNECTION_STRING. Current env: ")
        print(os.environ)
        # Fallback: Dummy Models für Testing
        gradient_model = lambda x: [3600.0]
        linear_model = lambda x: [3600.0]

def din33466(uphill, downhill, distance):
    km = distance / 1000.0
    vertical = downhill / 500.0 + uphill / 300.0
    horizontal = km / 4.0
    return 3600.0 * (min(vertical, horizontal) / 2 + max(vertical, horizontal))

def sac(uphill, downhill, distance):
    km = distance / 1000.0
    return 3600.0 * (uphill/400.0 + km /4.0)

def timedelta_minutes(seconds):
    rounded_minutes = int(round(seconds / 60.0))
    return str(datetime.timedelta(minutes=rounded_minutes))

print("\n*** Flask Backend (Production Ready) ***")
app = Flask(__name__)
cors = CORS(app)
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
        return send_file("../frontend/build/" + path)
    except FileNotFoundError:
        return send_file("../frontend/build/index.html")

@app.route("/api/predict")
def hello_world():
    # Models lazy laden
    download_models()
    
    downhill = request.args.get('downhill', default = 0, type = int)
    uphill = request.args.get('uphill', default = 0, type = int)
    length = request.args.get('length', default = 0, type = int)

    demoinput = [[downhill,uphill,length,0]]
    demodf = pd.DataFrame(columns=['downhill', 'uphill', 'length_3d', 'max_elevation'], data=demoinput)
    gradient_prediction = gradient_model.predict(demodf)[0]
    linear_prediction = linear_model.predict(demodf)[0]

    return jsonify({
        'time': timedelta_minutes(gradient_prediction),
        'linear': timedelta_minutes(linear_prediction),
        'din33466': timedelta_minutes(din33466(uphill=uphill, downhill=downhill, distance=length)),
        'sac': timedelta_minutes(sac(uphill=uphill, downhill=downhill, distance=length))
    })

# PRODUCTION SERVER - Kein Development Warning!
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 80))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )