import http.server
import json
import math
import socketserver
import time
import webbrowser
from datetime import datetime, timezone, timedelta
import ephem
import requests

PORT = 8080
LAT_RB = -9.9753
LON_RB = -67.8249
ELEV_RB = 153.0

RIO_BRANCO = ephem.Observer()
RIO_BRANCO.lat = str(LAT_RB)
RIO_BRANCO.lon = str(LON_RB)
RIO_BRANCO.elevation = ELEV_RB

TLE_CACHE = {"tle": None, "timestamp": 0}

def get_tle():
    now = time.time()
    if TLE_CACHE["tle"] and (now - TLE_CACHE["timestamp"] < 3600):
        return TLE_CACHE["tle"]
    try:
        url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
        r = requests.get(url, timeout=10)
        lines = [l.strip() for l in r.text.strip().split("\n") if l.strip()]
        if len(lines) >= 3:
            tle = (lines[0], lines[1], lines[2])
            TLE_CACHE["tle"] = tle
            TLE_CACHE["timestamp"] = now
            return tle
    except Exception:
        pass
    if TLE_CACHE["tle"]:
        return TLE_CACHE["tle"]
    return (
        "ISS (ZARYA)",
        "1 25544U 98067A   24001.00000000  .00016717  00000-0  10270-3 0  9001",
        "2 25544  51.6400 208.5000 0004500 120.0000 240.0000 15.49800000400001"
    )

def get_orbital_path(iss, hours=24, step_mins=5):
    steps = int((hours * 60) / step_mins)
    points = []
    base_time = datetime.now(timezone.utc)
    for i in range(steps):
        t = base_time + timedelta(minutes=i * step_mins)
        iss.compute(t.strftime("%Y/%m/%d %H:%M:%S"))
        points.append([math.degrees(iss.sublat), math.degrees(iss.sublong)])
    return points

def get_next_pass(iss):
    try:
        RIO_BRANCO.date = ephem.now()
        tr, azr, tt, altt, ts, azs = RIO_BRANCO.next_pass(iss)
        if tr:
            t_utc = tr.datetime().replace(tzinfo=timezone.utc)
            t_acre = t_utc - timedelta(hours=5)
            seconds_left = max(0, int((t_utc - datetime.now(timezone.utc)).total_seconds()))
            return {
                "next_pass_utc": t_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "next_pass_acre": t_acre.strftime("%Y-%m-%d %H:%M:%S (UTC-5)"),
                "seconds_left": seconds_left,
                "max_altitude": round(math.degrees(altt), 1)
            }
    except Exception:
        pass
    return {"next_pass_utc": "N/D", "next_pass_acre": "N/D", "seconds_left": 0, "max_altitude": 0}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛰️ ISS Tracker HD - Rio Branco / Acre</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body, html { margin: 0; padding: 0; height: 100%; font-family: monospace; background: #0b0e14; color: #fff; }
        #map { width: 100%; height: 100%; }
        .panel {
            position: absolute; top: 10px; left: 10px; z-index: 1000;
            background: rgba(11, 14, 20, 0.85); backdrop-filter: blur(8px);
            padding: 14px; border-radius: 8px; border: 1px solid #1f293d;
            max-width: 320px; font-size: 12px; line-height: 1.4;
        }
        h2 { margin: 0 0 8px 0; font-size: 14px; color: #38bdf8; }
        .highlight { color: #4ade80; font-weight: bold; }
        .radio-box { margin-top: 8px; border-top: 1px dashed #334155; padding-top: 8px; color: #cbd5e1; font-size: 11px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="panel">
        <h2>🛰️ ISS TELEMETRIA AO VIVO</h2>
        <div><b>Latitude:</b> <span id="lat" class="highlight">--</span></div>
        <div><b>Longitude:</b> <span id="lon" class="highlight">--</span></div>
        <div><b>Altitude:</b> <span id="alt" class="highlight">--</span> km</div>
        <div><b>Velocidade:</b> ~27.600 km/h</div>
        <hr style="border:0; border-top:1px solid #1f293d; margin:8px 0;">
        <div><b>Passagem em Rio Branco - AC:</b></div>
        <div>Contagem: <span id="countdown" class="highlight">--</span></div>
        <div>Horário Local: <span id="pass-time">--</span></div>
        <div class="radio-box">
            <b>📻 Rádio ARISS:</b><br>
            • Voz FM: 145.800 Down / 145.200 Up<br>
            • Repetidora: 437.800 Down / 145.990 Up<br>
            • APRS: 145.825 MHz | SSTV: 145.800 MHz
        </div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const map = L.map('map').setView([0, 0], 3);
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Esri World Imagery', maxZoom: 17
        }).addTo(map);

        const issIcon = L.divIcon({
            html: '<div style="font-size: 24px; text-shadow: 0 0 10px #38bdf8;">🛰️</div>',
            className: 'iss-marker', iconSize: [30, 30], iconAnchor: [15, 15]
        });

        let issMarker = L.marker([0, 0], { icon: issIcon }).addTo(map);
        let footprintCircle = L.circle([0, 0], { radius: 2200000, color: '#38bdf8', fillOpacity: 0.1, weight: 1 }).addTo(map);
        let orbitLine = L.polyline([], { color: '#ef4444', weight: 1.5, opacity: 0.7 }).addTo(map);

        L.marker([-9.9753, -67.8249]).addTo(map).bindPopup("📍 Rio Branco - Acre");

        function formatTime(s) {
            const h = Math.floor(s / 3600);
            const m = Math.floor((s % 3600) / 60);
            const sec = s % 60;
            return `${h}h ${m}m ${sec}s`;
        }

        async function update() {
            try {
                const res = await fetch('/api/telemetry');
                const d = await res.json();
                document.getElementById('lat').innerText = d.lat.toFixed(4);
                document.getElementById('lon').innerText = d.lon.toFixed(4);
                document.getElementById('alt').innerText = d.alt.toFixed(1);
                document.getElementById('countdown').innerText = formatTime(d.pass.seconds_left);
                document.getElementById('pass-time').innerText = d.pass.next_pass_acre;

                issMarker.setLatLng([d.lat, d.lon]);
                footprintCircle.setLatLng([d.lat, d.lon]);
                if (d.orbit && d.orbit.length) orbitLine.setLatLngs(d.orbit);
            } catch (e) {}
        }
        setInterval(update, 1000);
        update();
    </script>
</body>
</html>
"""

class ISSHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/telemetry":
            tle = get_tle()
            iss = ephem.readtle(tle[0], tle[1], tle[2])
            iss.compute(datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S"))
            data = {
                "lat": math.degrees(iss.sublat),
                "lon": math.degrees(iss.sublong),
                "alt": iss.elevation / 1000.0,
                "orbit": get_orbital_path(iss, hours=24, step_mins=5),
                "pass": get_next_pass(iss)
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_error(404)

if __name__ == "__main__":
    webbrowser.open(f"http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), ISSHandler) as httpd:
        print(f"🛰️ ISS Tracker rodando em http://localhost:{PORT}")
        httpd.serve_forever()
