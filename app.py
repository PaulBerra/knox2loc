from flask import Flask, jsonify, render_template, request
import requests
import sys
import os
import json

app = Flask(__name__)
url_base = "https://eu01.manage.samsungknox.com/emm"


def load_config(path="config.json"):
    """
    Charge client_id@tenant_id et client_secret depuis config.json.
    """
    if not os.path.exists(path):
        sys.exit(f"[ERROR] Le fichier '{path}' est introuvable.")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "userID_full" not in cfg or "client_secret" not in cfg:
        sys.exit("[ERROR] Clés manquantes dans config.json (userID_full et client_secret requis).")
    return cfg


def get_bearer():
    """
    Récupère le token Bearer via /oauth/token (grant_type=client_credentials).
    """
    cfg = load_config()
    token_url = f"{url_base}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": cfg["userID_full"],
        "client_secret": cfg["client_secret"]
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(token_url, data=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_device_list(bearer, limit=1000, start=0):
    """
    Récupère une page d'appareils actifs (deviceStatus=A).
    Renvoie le JSON complet tel que reçu par Knox Manage.
    """
    endpoint = f"{url_base}/oapi/device/selectDeviceList"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "limit": limit,
        "start": start,
        "deviceStatus": "A"
    }
    resp = requests.post(endpoint, data=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_voles_devices_full():
    """
    Récupère dynamiquement tous les appareils actifs ET marqués “volé”.
    Renvoie une liste de dictionnaires, chacun contenant :
      - deviceId
      - deviceName (mobileId)
      - deviceModelKind
    Utile pour la liste latérale.
    """
    bearer = get_bearer()
    voles = []
    start = 0
    page_size = 1000

    while True:
        data = fetch_device_list(bearer, limit=page_size, start=start)
        if data.get("resultCode") != "0":
            sys.exit(f"[ERROR] selectDeviceList a échoué : {data}")

        devices = data.get("resultValue", {}).get("deviceList", [])
        if not isinstance(devices, list):
            sys.exit("[ERROR] La clé 'deviceList' n'est pas un tableau.")

        for dev in devices:
            # Si un des tags vaut "volé", on conserve l'objet minimal
            tags_list = dev.get("deviceTags", [])
            for t in tags_list:
                if t.get("tagValue") == "volé":
                    voles.append({
                        "deviceId": dev.get("deviceId"),
                        "deviceName": dev.get("userName"),         # correspond à mobileId
                        "deviceModelKind": dev.get("deviceModel") # modèle du téléphone
                    })
                    break

        if len(devices) < page_size:
            break
        start += page_size

    # On supprime d’éventuels doublons (même deviceId)
    unique = { d["deviceId"]: d for d in voles }
    return list(unique.values())


def get_device_location(bearer, device_id):
    """
    Récupère la localisation en direct d’un appareil grâce à /selectDeviceLocation.
    Renvoie {deviceId, latitude, longitude, lastUpdate} ou None si erreur.
    """
    endpoint = f"{url_base}/oapi/device/selectDeviceLocation"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {"deviceId": device_id}
    try:
        resp = requests.post(endpoint, data=payload, headers=headers)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    data = resp.json()
    if data.get("resultCode") != "0":
        return None

    rv = data.get("resultValue", {})
    try:
        lat = float(rv.get("latitude"))
        lon = float(rv.get("longitude"))
    except (TypeError, ValueError):
        return None

    last_update = rv.get("stdFormatUpdated")  # ex. "2025-05-19T21:41:33Z"
    return {
        "deviceId": device_id,
        "latitude": lat,
        "longitude": lon,
        "lastUpdate": last_update
    }


@app.route("/api/devices")
def api_devices():
    """
    Renvoie la liste structurée de tous les appareils "volé" :
    [
      { "deviceId": "...", "deviceName": "...", "deviceModelKind": "..." },
      ...
    ]
    """
    return jsonify(get_voles_devices_full())


@app.route("/api/locations")
def api_locations():
    """
    Renvoie la liste des localisations en direct pour chaque appareil "volé".
    Mis à jour automatiquement toutes les 10 s (sur le front-end), ou manuellement via /api/refresh/<id>.
    """
    bearer = get_bearer()
    # Récupérer la liste dynamique de deviceId volés
    voles = get_voles_devices_full()
    result = []
    for dev in voles:
        dev_id = dev["deviceId"]
        loc = get_device_location(bearer, dev_id)
        if loc:
            result.append(loc)
    return jsonify(result)


@app.route("/api/refresh/<device_id>", methods=["POST"])
def api_refresh_device(device_id):
    """
    Force une requête unique à /selectDeviceLocation pour l'appareil donné.
    Renvoie directement le résultat de localisation pour ce device_id, ou 404 si introuvable.
    """
    bearer = get_bearer()

    # Vérifier d'abord que device_id existe bien dans la liste "volé"
    voles = get_voles_devices_full()
    valid_ids = { d["deviceId"] for d in voles }
    if device_id not in valid_ids:
        return jsonify({"error": "Device ID non connu ou non marqué 'volé'."}), 404

    loc = get_device_location(bearer, device_id)
    if not loc:
        return jsonify({"error": "Impossible de récupérer la localisation."}), 500

    return jsonify(loc)


@app.route("/")
def index():
    """
    Sert la page HTML contenant la carte et le volet latéral.
    """
    return render_template("index.html")


if __name__ == "__main__":
    # En dev : lancez python app.py → http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000, debug=True)
