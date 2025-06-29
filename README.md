**knox2loc Documentation**


![image](https://github.com/user-attachments/assets/2facff1d-3db9-4dc1-9d4d-e228ded6361d)



---

## Overview

These two scripts work together to provide real-time monitoring and alerting for stolen corporate mobile devices via the Knox API, as well as a web-based interface for visualizing their locations.

* **Email Alert Script**: Runs continuously in the background to detect when any device tagged as "stolen" reconnects to the network. Upon detection, it sends an HTML email notification with relevant details (timestamp, location, device info) to a designated security team.
* **Web Interface (Flask)**: Offers a dynamic, map-based dashboard listing all stolen devices and their current locations. It polls the Knox API periodically to update device positions (every 10 min by default) and allows manual refreshes for individual devices.

---

## 1. Email Alert Script

### 1.1 Purpose and Benefits

* **Continuous Monitoring**: Automatically polls the Knox API at regular intervals (every 2 minutes) to check the "last connection" timestamp for each device tagged as stolen. No manual dashboard checks are needed.
* **Contextual Notification**: Only triggers an email if a stolen device reconnects within a defined geographic area (e.g., within 10 km of Bordeaux). The email includes:

  * Device ID
  * User name
  * Device model
  * Connection timestamp (local time)
  * Latitude and longitude
  * Links to view on Google Maps
* **Rapid Response**: Security personnel receive immediate alerts, enabling them to remotely block the device, involve law enforcement, or take other mitigation measures without delay.
* **Automated Operation**: Deploy as a systemd service or cron job so that the script runs 24/7 without manual intervention.

### 1.2 Prerequisites

1. **Python 3 Environment**

   * Install Python 3 (version ≥ 3.7).
   * Install required packages:

     ```bash
     pip install requests
     ```
   * The `email` module is part of the standard library.

2. **Configuration File (`config.json`)**

   * Place `config.json` in the same directory as the script. It must include the following keys:

     ```json
     {
       "userID_full": "<client_id>@<tenant_id>", // Knox Api user
       "client_secret": "<Knox_client_secret>",  // Knox Api Secret
       "smtp_server": "smtp.example.com",
       "smtp_port": 587,
       "smtp_user": "alert@yourcompany.com",
       "smtp_password": "<SMTP_password>",
       "email_to": "security@yourcompany.com",
       "tagVol": "stolen",                      // tag extracted from tagValue to identify stolen but non-blocked phones
       "lat": "XXX",                            // coordinate of your juridiction (fast cops action)
       "lon": "XXX",                            // coordinate of your juridiction (fast cops action)
       "refresh": "120",                        // delay between refreshs
       "radius": "10"                           // radius of attention around lat / lon
     }
     ```
   * **`userID_full`** and **`client_secret`** come from your Knox Manage OAuth2 application credentials.
   * **SMTP settings** (server, port, username, password) must allow STARTTLS.
   * **`tagVol`** must match the exact tag value used in Knox to mark stolen devices (e.g., "stolen").

3. **Network Access to Knox API**

   * Ensure connectivity to the Knox endpoints:

     * `https://eu01.manage.samsungknox.com/emm/oauth/token`
     * `https://eu01.manage.samsungknox.com/emm/oapi/device/selectDeviceList`
     * `https://eu01.manage.samsungknox.com/emm/oapi/device/selectDeviceLocation`
   * Outbound HTTPS traffic on port 443 must be allowed.

4. **Knox Account with Proper Permissions**

   * The OAuth2 credentials must have read access to:

     * **Device list** (`selectDeviceList`)
     * **Device location** (`selectDeviceLocation`)
   * Devices must be tagged in Knox with the value specified by `tagVol` (e.g., "stolen").

5. **Service Setup**

   * Create a dedicated user (e.g., `knoxalert`) on the server to run the script.
   * Create a systemd service unit (or cron job) to launch the script at boot and restart on failure. Example systemd unit:

     ```ini
     [Unit]
     Description=knox2loc Email Monitoring Service

     [Service]
     Type=simple
     User=knoxalert
     WorkingDirectory=/opt/knox2loc
     ExecStart=/usr/bin/python3 alert_mail.py
     Restart=always

     [Install]
     WantedBy=multi-user.target
     ```
   * Enable and start:

     ```bash
     sudo systemctl daemon-reload
     sudo systemctl enable knox2loc.service
     sudo systemctl start knox2loc.service
     ```

6. **Logging Directory**

   * Create a folder (e.g., `/var/log/knox2loc/`) and grant write permissions to the `knoxalert` user.
   * The script prints warnings and errors to STDOUT; redirect or capture logs via systemd or cron configuration.

---

## 2. Web Interface (Flask)

### 2.1 Purpose and Benefits

* **Real-Time Dashboard**: Provides a dynamic view of all stolen devices and their latest locations, refreshed every 10 seconds (or manually via a refresh endpoint).
* **List and Map View**:

  * **`/api/devices`** endpoint returns a JSON array of all devices currently tagged as stolen, including `deviceId`, `deviceName`, and `deviceModelKind`.
  * **`/api/locations`** endpoint returns a JSON array of `{ deviceId, latitude, longitude, lastUpdate }` for each stolen device.
* **Manual Refresh**:

  * **`/api/refresh/<device_id>`** (POST) forces a single Knox API call to refresh the location of the specified device.
* **User-Friendly Front-End**:

  * The root route (`/`) serves an `index.html` (in the `templates/` folder) that loads:

    1. A map component (Leaflet or Google Maps).
    2. A sidebar listing all stolen devices (populated from `/api/devices`).
    3. JavaScript that polls `/api/locations` every 10 seconds to update markers on the map.
  * Operators can see device positions at a glance and click a button to manually refresh any single device’s location.

### 2.2 Prerequisites

1. **Python 3 Environment with Flask and Requests**

   * Install Flask and Requests:

     ```bash
     pip install flask requests
     ```
   * Project directory structure should include:

     ```text
     /opt/knox2loc
     ├── app.py
     ├── config.json  # Must have userID_full and client_secret
     ├── templates/
     │   └── index.html
     └── static/
         ├── main.css   # (optional)
         └── main.js    # (optional)
     ```

2. **Configuration File (`config.json`)**

   * Place `config.json` in the same directory as `app.py`. It must contain:

     ```json
     {
       "userID_full": "<client_id>@<tenant_id>",
       "client_secret": "<Knox_client_secret>"
     }
     ```
   * No SMTP credentials are needed for the web interface.

3. **Templating and Static Files**

   * **`templates/index.html`** must include:

     * A `<div id="map"></div>` for the map container.
     * A `<div id="sidebar"></div>` listing devices.
     * JavaScript that:

       * Fetches `/api/devices` on page load to populate the sidebar.
       * Every 10 seconds, fetches `/api/locations` and updates map markers.
       * For each device in the sidebar, provides a "Refresh" button to POST `/api/refresh/<deviceId>`.
   * Optionally include CSS/JS in `static/main.css` and `static/main.js`. If using Leaflet:

     ```html
     <!-- In <head> of index.html -->
     <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
     <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
     ```
   * If using Google Maps, insert:

     ```html
     <script src="https://maps.googleapis.com/maps/api/js?key=YOUR_API_KEY"></script>
     ```

4. **Server Hosting**

   * In development, run:

     ```bash
     python app.py
     ```

     → accessible at `http://127.0.0.1:5000/`.
   * In production, use a WSGI server (Gunicorn or uWSGI) behind a reverse proxy (Nginx or Apache). Example systemd unit using Gunicorn:

     ```ini
     [Unit]
     Description=knox2loc Flask Web Service
     After=network.target

     [Service]
     Type=simple
     User=knoxalert
     WorkingDirectory=/opt/knox2loc
     ExecStart=/usr/bin/gunicorn --bind 0.0.0.0:5000 app:app
     Restart=always

     [Install]
     WantedBy=multi-user.target
     ```
   * Enable and start:

     ```bash
     sudo systemctl enable knox2loc-web.service
     sudo systemctl start knox2loc-web.service
     ```

5. **Knox API Access**

   * Knox OAuth2 credentials (same as Email Alert Script) must have read access to device list and locations.
   * Ensure network connectivity (outbound HTTPS) to Knox endpoints from the server.

6. **Firewall and DNS**

   * Open port 5000 (or whichever port Gunicorn listens on) on the server’s firewall.
   * (Optional) Configure a DNS record (e.g., `knox-alert.company.local`) pointing to the server IP.

---

## 3. Deployment and Usage Workflow

1. **Server Preparation**

   * Provision a Linux server (Ubuntu/Debian or CentOS/RHEL).
   * Create a dedicated user: `sudo adduser --system --no-create-home knoxalert`.
   * Install Python 3, pip, and necessary OS packages:

     ```bash
     sudo apt update
     sudo apt install -y python3 python3-pip python3-venv
     ```

2. **Clone or Copy the Project**

   ```bash
   sudo mkdir /opt/knox2loc
   sudo chown knoxalert:knoxalert /opt/knox2loc
   cd /opt/knox2loc
   # Copy alert_mail.py, app.py, config.json, templates/, static/ here
   ```

3. **Install Python Dependencies**

   ```bash
   sudo -u knoxalert python3 -m venv venv
   sudo -u knoxalert venv/bin/pip install flask requests
   ```

4. **Configure `config.json`**

   * Edit `/opt/knox2loc/config.json` with Knox OAuth2 and SMTP settings for the email script.

5. **Set Up Email Alert Service**

   * Create `/etc/systemd/system/knox2loc-email.service`:

     ```ini
     [Unit]
     Description=knox2loc Email Monitoring Service

     [Service]
     Type=simple
     User=knoxalert
     WorkingDirectory=/opt/knox2loc
     ExecStart=/opt/knox2loc/venv/bin/python3 /opt/knox2loc/alert_mail.py
     Restart=always

     [Install]
     WantedBy=multi-user.target
     ```
   * Enable and start:

     ```bash
     sudo systemctl daemon-reload
     sudo systemctl enable knox2loc-email.service
     sudo systemctl start knox2loc-email.service
     ```

6. **Set Up Web Interface Service**

   * Create `/etc/systemd/system/knox2loc-web.service`:

     ```ini
     [Unit]
     Description=knox2loc Flask Web Service
     After=network.target

     [Service]
     Type=simple
     User=knoxalert
     WorkingDirectory=/opt/knox2loc
     ExecStart=/opt/knox2loc/venv/bin/gunicorn --bind 0.0.0.0:5000 app:app
     Restart=always

     [Install]
     WantedBy=multi-user.target
     ```
   * Enable and start:

     ```bash
     sudo systemctl daemon-reload
     sudo systemctl enable knox2loc-web.service
     sudo systemctl start knox2loc-web.service
     ```

7. **Accessing the Dashboard**

   * Open a browser to `http://<server_ip>:5000/` (or your configured DNS name).
   * The sidebar shows all stolen devices, and the map displays their latest locations, updated every 10 seconds.
   * Click “Refresh” next to any device to force an immediate location query.

---

### Key Checklist

| Item                                       | Status/Notes                                                |
| ------------------------------------------ | ----------------------------------------------------------- |
| Python 3 + Dependencies Installed          | `requests`, `flask`                                         |
| `config.json` (Email)                      | Contains Knox OAuth2 + SMTP settings                        |
| `config.json` (Web)                        | Contains Knox OAuth2                                        |
| Knox API Credentials                       | Read access to device list and location                     |
| Email SMTP Account                         | Able to send STARTTLS emails to security distribution       |
| `alert_mail.py` Running as Systemd Service | Enabled: `knox2loc-email.service`                      |
| `app.py` Running via Gunicorn Systemd      | Enabled: `knox2loc-web.service`, port 5000 open        |
| Front-End Templates/Static Files           | `templates/index.html`, `static/main.css`, `static/main.js` |
| Firewall & DNS                             | Port 5000 reachable; optional DNS entry configured          |

---

With this setup, your security team gains:

1. **Instant email alerts** whenever a stolen device comes back online in a critical area.
2. **A real-time map dashboard** to track stolen devices’ locations, enabling faster decision-making and coordination.
