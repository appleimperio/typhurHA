#!/usr/bin/env python3
"""
Typhur Bridge - Home Assistant Add-on
Kobler Typhur Sync Quad til HA via MQTT med auto-discovery.
Henter MQTT-sertifikater automatisk fra Typhur API.
"""
import json
import ssl
import time
import logging
import hashlib
import uuid
import os
import subprocess
import tempfile
import requests
import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("typhur_bridge")

OPTIONS_FILE = "/data/options.json"
DATA_DIR = "/data"
CERT_FILE = os.path.join(DATA_DIR, "typhur_client.crt")
KEY_FILE = os.path.join(DATA_DIR, "typhur_client.key")
CLIENT_ID_FILE = os.path.join(DATA_DIR, "typhur_client_id.txt")
TOKEN_FILE = os.path.join(DATA_DIR, "typhur_token.txt")

TYPHUR_BROKER = "a2qg0p56us3mxs-ats.iot.eu-central-1.amazonaws.com"
TYPHUR_PORT = 8883
TYPHUR_API = "https://api.iot.typhur.de"
APP_KEY = "7d02d81bd7f4483a9a0ac580f2b6ad44"
APP_ID = "ap206cba3069ed4a11"
APP_VERSION = "4200"
APP_DEVICE_SN = hashlib.md5(b"ha_typhur_bridge_v1").hexdigest()  # 32-char hex
HA_DISCOVERY_PREFIX = "homeassistant"


def load_options():
    with open(OPTIONS_FILE) as f:
        return json.load(f)


def sign_request(token, body_str="{}"):
    nonce = uuid.uuid4().hex
    timestamp = str(int(time.time() * 1000))
    headers_sorted = [
        ("x-appId", APP_ID), ("x-appVersion", APP_VERSION),
        ("x-deviceSn", APP_DEVICE_SN), ("x-lang", "en_US"),
        ("x-nonce", nonce), ("x-region", "NO"),
        ("x-timestamp", timestamp),
    ]
    # x-token inkluderes kun når den faktisk finnes
    if token:
        headers_sorted.append(("x-token", token))
    parts = ";".join(f"{k}={v}" for k, v in headers_sorted)
    sign_str = f"{APP_KEY}|{parts}|{body_str}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    h = {k: v for k, v in headers_sorted}
    h["x-sign"] = sign
    h["Content-Type"] = "application/json"
    return h


def login(email, password):
    """Logg inn med e-post og passord, returner token. Prøver MD5-hashet passord først."""
    body = json.dumps({"account": email, "password": hashlib.md5(password.encode()).hexdigest()}, separators=(",", ":"))
    resp = requests.post(
        f"{TYPHUR_API}/app/user/login",
        headers=sign_request("", body),
        data=body,
        timeout=15
    )
    data = resp.json()
    if data.get("code") == "0":
        token = data["data"]["token"]
        log.info("Innlogging vellykket, token hentet.")
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, 0o600)
        return token

    # Fallback: prøv med klartekst passord
    log.warning(f"MD5-innlogging feilet ({data.get('msg')}), prøver klartekst...")
    body2 = json.dumps({"account": email, "password": password}, separators=(",", ":"))
    resp2 = requests.post(
        f"{TYPHUR_API}/app/user/login",
        headers=sign_request("", body2),
        data=body2,
        timeout=15
    )
    data2 = resp2.json()
    if data2.get("code") == "0":
        token = data2["data"]["token"]
        log.info("Innlogging vellykket (klartekst), token hentet.")
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, 0o600)
        return token

    raise Exception(f"Innlogging feilet: {data2.get('msg')} (kode: {data2.get('code')})")


def resolve_token(options):
    """Hent token fra config, cachet fil, eller logg inn med e-post/passord."""
    # 1. Eksplisitt token i config
    token = (options.get("typhur_token") or "").strip()
    if token:
        log.info("Bruker token fra konfigurasjon.")
        return token

    # 2. Cachet token fra forrige innlogging
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            cached = f.read().strip()
        if cached:
            log.info("Bruker cachet token fra /data/typhur_token.txt")
            return cached

    # 3. Logg inn med e-post og passord
    email = (options.get("typhur_email") or "").strip()
    password = (options.get("typhur_password") or "").strip()
    if email and password:
        log.info(f"Logger inn som {email}...")
        return login(email, password)

    raise Exception(
        "Ingen token funnet! Fyll inn enten 'typhur_token' eller 'typhur_email' + 'typhur_password' i konfigurasjonen."
    )


def fetch_and_save_certs(token):
    """Hent MQTT-sertifikater fra Typhur API og lagre i /data/"""
    log.info("Henter MQTT-sertifikater fra Typhur API...")
    resp = requests.post(
        f"{TYPHUR_API}/app/mqtt/cert/apply",
        headers=sign_request(token, "{}"),
        data="{}",
        timeout=15
    )
    data = resp.json()
    if data.get("code") != "0":
        raise Exception(f"Cert apply feilet: {data.get('msg')}")

    cert_data = data["data"]
    p12_url = cert_data["p12Url"]
    p12_password = cert_data["p12Password"]
    client_id = cert_data["clientId"]

    p12_resp = requests.get(p12_url, timeout=15)
    p12_tmp = tempfile.NamedTemporaryFile(suffix=".p12", delete=False)
    p12_tmp.write(p12_resp.content)
    p12_tmp.close()

    subprocess.run([
        "openssl", "pkcs12", "-legacy",
        "-in", p12_tmp.name,
        "-passin", f"pass:{p12_password}",
        "-nokeys", "-out", CERT_FILE, "-nodes"
    ], check=True, capture_output=True)

    subprocess.run([
        "openssl", "pkcs12", "-legacy",
        "-in", p12_tmp.name,
        "-passin", f"pass:{p12_password}",
        "-nocerts", "-out", KEY_FILE, "-nodes"
    ], check=True, capture_output=True)

    os.unlink(p12_tmp.name)
    os.chmod(KEY_FILE, 0o600)

    with open(CLIENT_ID_FILE, "w") as f:
        f.write(client_id)

    log.info(f"Sertifikater lagret. Client ID: {client_id}")
    return client_id


def get_devices(token):
    resp = requests.post(
        f"{TYPHUR_API}/app/device/bind/list",
        headers=sign_request(token, "{}"),
        data="{}",
        timeout=10
    )
    data = resp.json()
    if data.get("code") == "0":
        return data.get("data", [])
    return []


def publish_discovery(ha_client, device):
    device_id = str(device["deviceId"])
    device_name = device.get("deviceName", "Typhur Sync Quad")
    device_model = device.get("deviceModel", "WT08")
    state_topic = f"typhur/{device_id}/state"

    device_info = {
        "identifiers": [f"typhur_{device_id}"],
        "name": device_name,
        "manufacturer": "Typhur",
        "model": device_model,
    }

    probes = (device.get("lastStatusCmd") or {}).get("cmdData", {}).get("probes", [])
    if not probes:
        probes = [{"probeColor": f"probe{i}"} for i in range(1, 5)]

    sensors = []

    for probe in probes:
        color = probe.get("probeColor", "probe1")
        label = color.replace("probe", "Probe ")
        base = f"(value_json.cmdData.probes | selectattr('probeColor','eq','{color}') | list | first)"
        sensors += [
            {
                "uid": f"typhur_{device_id}_{color}_temp",
                "name": f"{device_name} {label} Temperatur",
                "unit": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "value_template": f"{{{{ (({base}.curTemperature | float) / 10 - 32) * 5 / 9 | round(1) }}}}",
            },
            {
                "uid": f"typhur_{device_id}_{color}_ambient",
                "name": f"{device_name} {label} Omgivelsestemperatur",
                "unit": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "value_template": f"{{{{ (({base}.curAmbientTemperature | float) / 10 - 32) * 5 / 9 | round(1) }}}}",
            },
            {
                "uid": f"typhur_{device_id}_{color}_battery",
                "name": f"{device_name} {label} Batteri",
                "unit": "%",
                "device_class": "battery",
                "state_class": "measurement",
                "value_template": f"{{{{ {base}.batteryValue }}}}",
            },
            {
                "uid": f"typhur_{device_id}_{color}_state",
                "name": f"{device_name} {label} Status",
                "unit": None,
                "device_class": None,
                "state_class": None,
                "value_template": f"{{{{ {base}.cookingState }}}}",
            },
        ]

    sensors += [
        {
            "uid": f"typhur_{device_id}_battery",
            "name": f"{device_name} Batteri",
            "unit": "%",
            "device_class": "battery",
            "state_class": "measurement",
            "value_template": "{{ value_json.cmdData.batteryValue }}",
        },
        {
            "uid": f"typhur_{device_id}_wifi",
            "name": f"{device_name} WiFi Signal",
            "unit": "dBm",
            "device_class": "signal_strength",
            "state_class": "measurement",
            "value_template": "{{ value_json.cmdData.wifiRssi }}",
        },
    ]

    for s in sensors:
        payload = {
            "name": s["name"],
            "unique_id": s["uid"],
            "state_topic": state_topic,
            "value_template": s["value_template"],
            "device": device_info,
        }
        if s.get("unit"):
            payload["unit_of_measurement"] = s["unit"]
        if s.get("device_class"):
            payload["device_class"] = s["device_class"]
        if s.get("state_class"):
            payload["state_class"] = s["state_class"]

        ha_client.publish(
            f"{HA_DISCOVERY_PREFIX}/sensor/{s['uid']}/config",
            json.dumps(payload),
            retain=True
        )

    log.info(f"Discovery publisert for {device_name} ({len(sensors)} sensorer)")
    return state_topic


class TyphurBridge:
    def __init__(self, options):
        self.options = options
        self.token = resolve_token(options)
        self.ha_client = None
        self.typhur_client = None
        self.devices = []

    def setup_ha_mqtt(self):
        self.ha_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="typhur_bridge_ha")
        if self.options.get("mqtt_username"):
            self.ha_client.username_pw_set(
                self.options["mqtt_username"],
                self.options.get("mqtt_password", "")
            )
        self.ha_client.connect(self.options["mqtt_host"], self.options["mqtt_port"], 60)
        self.ha_client.loop_start()
        log.info(f"Tilkoblet HA MQTT: {self.options['mqtt_host']}:{self.options['mqtt_port']}")

    def setup_typhur_mqtt(self, client_id):
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                for dev in self.devices:
                    device_id = str(dev["deviceId"])
                    device_model = dev.get("deviceModel", "WT08")
                    topic = f"device/{device_model}/{device_id}/pub"
                    client.subscribe(topic)
                    log.info(f"Abonnerer på: {topic}")
            else:
                log.error(f"Typhur MQTT feil rc={rc}")

        def on_message(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                if "status:report" not in data.get("cmdType", ""):
                    return
                for dev in self.devices:
                    device_id = str(dev["deviceId"])
                    device_model = dev.get("deviceModel", "WT08")
                    if f"device/{device_model}/{device_id}/pub" == msg.topic:
                        state_topic = f"typhur/{device_id}/state"
                        self.ha_client.publish(state_topic, msg.payload.decode())
                        break
            except Exception as e:
                log.error(f"Meldingsfeil: {e}")

        def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
            log.warning(f"Typhur MQTT frakoblet (rc={rc}), reconnect om 15s...")
            time.sleep(15)
            try:
                client.reconnect()
            except Exception as e:
                log.error(f"Reconnect feilet: {e}")

        self.typhur_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id
        )
        self.typhur_client.on_connect = on_connect
        self.typhur_client.on_message = on_message
        self.typhur_client.on_disconnect = on_disconnect

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        self.typhur_client.tls_set_context(ssl_ctx)
        self.typhur_client.connect(TYPHUR_BROKER, TYPHUR_PORT, 60)
        self.typhur_client.loop_start()
        log.info(f"Tilkoblet Typhur cloud MQTT")

    def run(self):
        log.info("=== Typhur Bridge starter ===")

        # Hent eller refresh sertifikater
        if not (os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)):
            client_id = fetch_and_save_certs(self.token)
        else:
            log.info("Bruker lagrede sertifikater")
            if os.path.exists(CLIENT_ID_FILE):
                with open(CLIENT_ID_FILE) as f:
                    client_id = f.read().strip()
            else:
                client_id = fetch_and_save_certs(self.token)

        # Hent enheter (med automatisk token-refresh ved auth-feil)
        log.info("Henter enhetsliste...")
        self.devices = get_devices(self.token)
        if not self.devices:
            email = (self.options.get("typhur_email") or "").strip()
            password = (self.options.get("typhur_password") or "").strip()
            if email and password:
                log.warning("Ingen enheter funnet — token kan ha utløpt. Prøver ny innlogging...")
                if os.path.exists(TOKEN_FILE):
                    os.unlink(TOKEN_FILE)
                self.token = login(email, password)
                self.devices = get_devices(self.token)
            if not self.devices:
                log.error("Ingen enheter funnet! Sjekk brukernavn/passord eller typhur_token.")
                raise SystemExit(1)
        log.info(f"Fant {len(self.devices)} enhet(er)")

        self.setup_ha_mqtt()
        self.setup_typhur_mqtt(client_id)

        # Publiser discovery for alle enheter
        time.sleep(2)
        for dev in self.devices:
            publish_discovery(self.ha_client, dev)

        log.info("Bridge kjører! Temperaturer sendes til Home Assistant.")

        while True:
            time.sleep(60)


if __name__ == "__main__":
    options = load_options()
    bridge = TyphurBridge(options)
    bridge.run()
