#!/usr/bin/env python3
import os
import sys
import json
import time
import requests
import smtplib
import math
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone,timedelta

# ------------------------------------------------------------
# --- Chargement de la configuration Knox + SMTP depuis JSON ---
# ------------------------------------------------------------
def load_config(path="config.json"):
    if not os.path.exists(path):
        sys.exit(f"[ERROR] Le fichier '{path}' est introuvable.")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Vérifier que toutes les clés nécessaires sont présentes
    for key in (
        "userID_full",
        "client_secret",
        "smtp_server",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "email_to",
        "tagVol",
        "lat",
        "lon",
        "refresh",
        "radius"
    ):
        if key not in cfg:
            sys.exit(f"[ERROR] Clé '{key}' manquante dans config.json.")
    return cfg

# ------------------------------------------------------------
# --- Récupération du token Bearer Knox Manage (OAuth2)      ---
# ------------------------------------------------------------
def get_bearer(cfg):
    token_url = "https://eu01.manage.samsungknox.com/emm/oauth/token"
    payload = {
        "grant_type":    "client_credentials",
        "client_id":     cfg["userID_full"],
        "client_secret": cfg["client_secret"]
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(token_url, data=payload, headers=headers)
    resp.raise_for_status()
    j = resp.json()
    return j["access_token"]

# ------------------------------------------------------------
# --- Récupère une page d'appareils actifs (deviceStatus=A) ---
# ------------------------------------------------------------
def fetch_device_list(bearer, limit=1000, start=0):
    endpoint = "https://eu01.manage.samsungknox.com/emm/oapi/device/selectDeviceList"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type":  "application/x-www-form-urlencoded"
    }
    payload = {
        "limit":        limit,
        "start":        start,
        "deviceStatus": "A"
    }
    resp = requests.post(endpoint, data=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()

# ------------------------------------------------------------
# --- Renvoie dict { deviceId: {last, userName, deviceModel} } ---
# --- pour tous les appareils tagués "volé"                ---
# ------------------------------------------------------------
def get_voles_with_lastcfg(bearer, tagVol):
    """
    Pour chaque device tagué "volé", on retourne un dict :
      deviceId -> { 
          "last":      ISO string de lastConnectionDate, 
          "userName":  dev["userName"], 
          "deviceModel": dev["deviceModelKind"] 
      }
    """
    start = 0
    page_size = 1000
    devices_info = {}  # { deviceId: {"last": iso_string, "userName": ..., "deviceModel": ...} }

    while True:
        data = fetch_device_list(bearer, limit=page_size, start=start)
        if data.get("resultCode") != "0":
            sys.exit(f"[ERROR] selectDeviceList a renvoyé une erreur : {data}")

        dev_list = data.get("resultValue", {}).get("deviceList", [])
        if not isinstance(dev_list, list):
            sys.exit("[ERROR] La clé 'deviceList' n'est pas un tableau.")

        for dev in dev_list:
            # Si l'appareil porte le tag "volé", on extrait ses champs
            for t in dev.get("deviceTags", []):
                if t.get("tagValue") == tagVol:
                    lcd = dev.get("lastConnectionDate")
                    if lcd and isinstance(lcd, dict):
                        try:
                            ts = int(lcd.get("time"))  # timestamp en ms UTC
                            # Conserver la date en ISO UTC "2025-06-04T12:34:56Z"
                            iso_dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                        except:
                            iso_dt = None
                    else:
                        iso_dt = None

                    device_id    = dev.get("deviceId")
                    user_name    = dev.get("userName", "—")
                    model        = dev.get("deviceModelKind", "—")

                    devices_info[device_id] = {
                        "last":        iso_dt,
                        "userName":    user_name,
                        "deviceModel": model
                    }
                    break

        if len(dev_list) < page_size:
            break
        start += page_size

    return devices_info

# ------------------------------------------------------------
# --- Envoi d'un mail en HTML via SMTP (STARTTLS)            ---
# ------------------------------------------------------------
def send_email(cfg, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["From"]    = cfg["smtp_user"]
    msg["To"]      = cfg["email_to"]
    msg["Subject"] = subject

    # On envoie uniquement la partie HTML dans ce cas
    part_html = MIMEText(html_body, "html")
    msg.attach(part_html)

    try:
        server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"])
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"[ERROR] Échec envoi email : {e}")

# ------------------------------------------------------------
# --- Appel Knox pour obtenir latitude/longitude du device  ---
# ------------------------------------------------------------
def get_device_location(bearer, device_id):
    endpoint = "https://eu01.manage.samsungknox.com/emm/oapi/device/selectDeviceLocation"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type":  "application/x-www-form-urlencoded"
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
        "deviceId":   device_id,
        "latitude":   lat,
        "longitude":  lon,
        "lastUpdate": last_update
    }

# ------------------------------------------------------------
# --- Haversine pour calculer distance (km) entre points    ---
# ------------------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # rayon Terre en km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ------------------------------------------------------------
# --- Test si lat/lon se situe dans un rayon de Bordeaux   ---
# ------------------------------------------------------------
def is_in_bordeaux(cfg, lat, lon, max_km=10):
    # Centre de Bordeaux approximatif
    bdx_lat = cfg["lat"]
    bdx_lon = cfg["lon"]
    return haversine(bdx_lat, bdx_lon, lat, lon) <= max_km

# ------------------------------------------------------------
# --- Boucle principale de surveillance et envoi d'alerte    ---
# ------------------------------------------------------------
def main_loop():
    cfg = load_config()
    bearer = get_bearer(cfg)

    # 1) État initial : pour chaque volé, on garde uniquement le timestamp ISO
    first_info = get_voles_with_lastcfg(bearer, cfg["tagVol"])
    last_seen_cache   = {}  # deviceId -> ISO string
    metadata_cache    = {}  # deviceId -> {userName, deviceModel}

    for did, info in first_info.items():
        last_seen_cache[did]  = info["last"]
        metadata_cache[did]   = {
            "userName":    info["userName"],
            "deviceModel": info["deviceModel"]
        }

    print("Surveillance démarrée. Appareils volés prêts à être surveillés.")

    # 2) Boucle infinie, mise à jour toutes les 2 minutes
    while True:
        try:
            time.sleep(int(cfg["refresh"]))
            # 2.1) Rafraîchir le token
            bearer = get_bearer(cfg)

            # 2.2) Nouvel état des volés
            new_info = get_voles_with_lastcfg(bearer, cfg["tagVol"])

            for deviceId, info in new_info.items():
                new_last = info["last"]
                old_last = last_seen_cache.get(deviceId)
                user_name = info["userName"]
                device_model = info["deviceModel"]

                # 2.3) Si nouvel allumage (aucune date auparavant ou date plus récente)
                if new_last and (old_last is None or new_last > old_last):
                    # On recherche la position GPS
                    loc = get_device_location(bearer, deviceId)
                    if loc is None:
                        print(f"[WARN] Impossible de récupérer localisation pour {deviceId}.")
                        last_seen_cache[deviceId] = new_last
                        metadata_cache[deviceId] = {
                            "userName": user_name,
                            "deviceModel": device_model
                        }
                        continue

                    lat = loc["latitude"]
                    lon = loc["longitude"]
                    # 2.4) Seulement si la position est < 10 km de Bordeaux
                    if is_in_bordeaux(cfg, lat, lon, max_km=int(cfg["radius"])):
                        # Formatage de la date pour l'e-mail (UTC+2)
                        dt_human = datetime.fromisoformat(new_last.replace("Z", "+00:00")) \
                            .astimezone(timezone(timedelta(hours=2))) \
                            .strftime("%d/%m/%Y %H:%M")
                        # Préparation du lien Google Maps
                        google_maps_url = f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"

                        subject = f"[ALERTE] Téléphone volé {deviceId} allumé à Bordeaux le {dt_human}"
                        # Corps HTML
                        html_body = f"""
                        <html>
                          <body>
                            <h2>⚠️ Alerte : téléphone volé allumé à Bordeaux ⚠️</h2>
                            <p>
                              <strong>Device ID :</strong> {deviceId}<br/>
                              <strong>Utilisateur :</strong> {user_name}<br/>
                              <strong>Modèle :</strong> {device_model}<br/>
                              <strong>Date de connexion :</strong> {dt_human} (UTC+2)<br/>
                              <strong>Latitude / Longitude :</strong> {lat:.6f}, {lon:.6f}
                            </p>
                            <p>
                              <a href="{google_maps_url}" target="_blank">
                                Voir sur Google Maps
                              </a>
                            </p>
                            <hr/>
                            <p>
                              Ce téléphone est géolocalisé à Bordeaux (rayon ≤ 10 km).<br/>
                              Vérifiez immédiatement la position précise sur votre dashboard.
                            </p>
                          </body>
                        </html>
                        ”
                        """
                        print(f"Envoi email pour {deviceId} (Bordeaux) : {subject}")
                        send_email(cfg, subject, html_body)
                    else:
                        print(f"[INFO] {deviceId} reconnecté hors de Bordeaux ({lat:.4f}, {lon:.4f}) → pas d'alerte.")

                # 2.5) Mise à jour du cache
                last_seen_cache[deviceId] = new_last
                metadata_cache[deviceId] = {
                    "userName":    user_name,
                    "deviceModel": device_model
                }

        except Exception as e:
            print(f"[WARN] Problème dans la boucle : {e}")
            continue

if __name__ == "__main__":
    main_loop()
