import dht
import machine
import network
import time
import json
import os
from umqtt.simple import MQTTClient
from ed25519 import keypair_from_seed, sign

# ── Config ────────────────────────────────────────────────
WIFI_SSID = "BSNL_FIBER_NIELIT"
WIFI_PASS = "Kokrajhar"
MQTT_BROKER = "192.168.1.168"
MQTT_PORT = 1883
MQTT_TOPIC = b"iot/data"
KEY_FILE = "device_key.bin"

# ── DHT11 setup ───────────────────────────────────────────
sensor = dht.DHT11(machine.Pin(4))

# ── Key management ────────────────────────────────────────
def get_or_create_keypair():
    try:
        with open(KEY_FILE, "rb") as f:
            private_key = f.read()
        public_key = private_key[32:]
        print("Loaded existing keypair")
    except:
        print("Generating new keypair...")
        seed = os.urandom(32)
        private_key, public_key = keypair_from_seed(seed)
        with open(KEY_FILE, "wb") as f:
            f.write(private_key)
        print("Keypair saved!")
    return private_key, public_key

# ── WiFi connect ──────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("Connecting to WiFi...")
    for i in range(20):
        if wlan.isconnected():
            print("WiFi connected! IP:", wlan.ifconfig()[0])
            return True
        time.sleep(1)
        print(".")
    print("WiFi failed!")
    return False

# ── Main loop ─────────────────────────────────────────────
def main():
    private_key, public_key = get_or_create_keypair()
    pub_hex = ''.join('{:02x}'.format(b) for b in public_key)
    DEVICE_DID = f"did:sol:{pub_hex}"
    print("DID:", DEVICE_DID)
    print("Public key:", pub_hex)

    if not connect_wifi():
        return

    client = MQTTClient("esp32_did_device", MQTT_BROKER, MQTT_PORT)
    client.connect()
    print("MQTT connected!")

    while True:
        try:
            sensor.measure()
            temp = sensor.temperature()
            hum = sensor.humidity()
            timestamp = time.time()

            payload = {
                "did": DEVICE_DID,
                "value": temp,
                "unit": "celsius",
                "humidity": hum,
                "timestamp": timestamp,
                "public_key": pub_hex
            }
            payload_str = json.dumps(payload)

            sig = sign(private_key, payload_str.encode())
            sig_hex = ''.join('{:02x}'.format(b) for b in sig)

            message = json.dumps({
                "payload": payload,
                "signature": sig_hex
            })

            client.publish(MQTT_TOPIC, message)
            print("Sent signed data:", temp, "C | sig:", sig_hex[:16], "...")

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

        time.sleep(10)

main()