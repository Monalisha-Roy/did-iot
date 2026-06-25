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
MQTT_BROKER = "LAPTOP-R1GUD2RE.local"
MQTT_PORT = 1883
MQTT_TOPIC = b"iot/data"
KEY_FILE = "device_key.bin"

# ── BMP280 setup ──────────────────────────────────────────
i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21))

class BMP280:
    def __init__(self, i2c, addr=0x76):
        self.i2c = i2c
        self.addr = addr
        self._load_calibration()

    def _read(self, reg, length):
        return self.i2c.readfrom_mem(self.addr, reg, length)

    def _load_calibration(self):
        data = self._read(0x88, 24)
        self.dig_T1 = data[1] << 8 | data[0]
        self.dig_T2 = self._s16(data[3] << 8 | data[2])
        self.dig_T3 = self._s16(data[5] << 8 | data[4])
        self.dig_P1 = data[7] << 8 | data[6]
        self.dig_P2 = self._s16(data[9] << 8 | data[8])
        self.dig_P3 = self._s16(data[11] << 8 | data[10])
        self.dig_P4 = self._s16(data[13] << 8 | data[12])
        self.dig_P5 = self._s16(data[15] << 8 | data[14])
        self.dig_P6 = self._s16(data[17] << 8 | data[16])
        self.dig_P7 = self._s16(data[19] << 8 | data[18])
        self.dig_P8 = self._s16(data[21] << 8 | data[20])
        self.dig_P9 = self._s16(data[23] << 8 | data[22])
        self.i2c.writeto_mem(self.addr, 0xF4, bytes([0x27]))
        self.i2c.writeto_mem(self.addr, 0xF5, bytes([0xA0]))

    def _s16(self, val):
        return val - 65536 if val > 32767 else val

    def read(self):
        data = self._read(0xF7, 6)
        raw_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        raw_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)

        # Temperature
        v1 = (raw_t / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        v2 = (raw_t / 131072.0 - self.dig_T1 / 8192.0) ** 2 * self.dig_T3
        t_fine = v1 + v2
        temp = t_fine / 5120.0

        # Pressure
        v1 = t_fine / 2.0 - 64000.0
        v2 = v1 * v1 * self.dig_P6 / 32768.0
        v2 = v2 + v1 * self.dig_P5 * 2.0
        v2 = v2 / 4.0 + self.dig_P4 * 65536.0
        v1 = (self.dig_P3 * v1 * v1 / 524288.0 + self.dig_P2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * self.dig_P1
        pressure = 1048576.0 - raw_p
        pressure = (pressure - v2 / 4096.0) * 6250.0 / v1
        v1 = self.dig_P9 * pressure * pressure / 2147483648.0
        v2 = pressure * self.dig_P8 / 32768.0
        pressure = pressure + (v1 + v2 + self.dig_P7) / 16.0

        return round(temp, 2), round(pressure / 100, 2)

sensor = BMP280(i2c)

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

    client = MQTTClient("esp32_bmp280", MQTT_BROKER, MQTT_PORT)
    client.connect()
    print("MQTT connected!")

    while True:
        try:
            temp, pressure = sensor.read()

            timestamp = int(time.time())

            payload = {
                "did": DEVICE_DID,
                "value": temp,
                "unit": "celsius",
                "pressure": pressure,
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
            print(f"Sent: {temp}C, {pressure}hPa | sig: {sig_hex[:16]}...")

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

        time.sleep(10)

main()