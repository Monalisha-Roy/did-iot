from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket
import asyncio
import json
import httpx
import os
import time
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from pydantic import BaseModel
from solana_client import generate_did, register_device_onchain, verify_device_onchain, revoke_device_onchain

load_dotenv()

PINATA_JWT = os.getenv("PINATA_JWT")
SOLANA_RPC = os.getenv("SOLANA_RPC")
PROGRAM_ID = os.getenv("PROGRAM_ID")
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iot/data")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connected WebSocket clients
ws_clients = []

# In-memory device registry
import os

DEVICES_FILE = "devices.json"

def load_devices():
    if os.path.exists(DEVICES_FILE):
        with open(DEVICES_FILE) as f:
            return json.load(f)
    return {}

def save_devices():
    with open(DEVICES_FILE, "w") as f:
        json.dump(devices, f)

devices = load_devices()

# ── Pydantic models ───────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    device_type: str
    location: str
    mac: str

# ── Broadcast to WebSocket clients ────────────────────────
async def broadcast(data: dict):
    for ws in ws_clients.copy():
        try:
            await ws.send_json(data)
        except:
            ws_clients.remove(ws)

# ── Upload data to Pinata IPFS ────────────────────────────
async def upload_to_pinata(payload: dict) -> str:
    headers = {
        "Authorization": f"Bearer {PINATA_JWT}",
        "Content-Type": "application/json",
    }
    body = {
        "pinataContent": payload,
        "pinataMetadata": {
            "name": f"iot-data-{payload.get('did', 'unknown')}-{payload.get('timestamp', '')}",
        },
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.pinata.cloud/pinning/pinJSONToIPFS",
            headers=headers,
            json=body,
            timeout=15,
        )
        result = response.json()
        cid = result.get("IpfsHash", "")
        print(f"[IPFS] Uploaded to Pinata. CID: {cid}")
        return cid

# ── Process incoming MQTT message ─────────────────────────
async def process_message_async(payload_str: str):
    try:
        msg = json.loads(payload_str)

        # Handle signed message format from ESP32
        if "payload" in msg:
            payload = msg["payload"]
            signature = msg.get("signature")
        else:
            payload = msg
            signature = None

        did = payload.get("did")
        value = payload.get("value")
        unit = payload.get("unit", "")
        timestamp = payload.get("timestamp", int(time.time()))

        if did not in devices:
            print(f"[REJECTED] Unknown DID: {did}")
            return

        device = devices[did]

        if device["status"] != "verified":
            print(f"[REJECTED] Device not verified: {did} (status: {device['status']})")
            await broadcast({
                "did": did,
                "device_name": device["name"],
                "device_type": device["type"],
                "value": f"{value} {unit}".strip(),
                "timestamp": timestamp,
                "hash": "rejected",
                "status": device["status"],
                "cid": None,
            })
            return

        pinata_payload = {
            "did": did,
            "device_name": device["name"],
            "device_type": device["type"],
            "value": value,
            "unit": unit,
            "timestamp": timestamp,
            "location": device["location"],
        }
        cid = await upload_to_pinata(pinata_payload)

        packet = {
            "did": did,
            "device_name": device["name"],
            "device_type": device["type"],
            "value": f"{value} {unit}".strip(),
            "timestamp": timestamp,
            "hash": hex(abs(hash(payload_str)))[:10],
            "status": "verified",
            "cid": cid,
            "ipfs_url": f"https://gateway.pinata.cloud/ipfs/{cid}" if cid else None,
        }

        print(f"[ACCEPTED] {device['name']}: {packet['value']} | CID: {cid}")
        await broadcast(packet)

    except Exception as e:
        print(f"[ERROR] {e}")

def process_message(payload_str: str):
    asyncio.run(process_message_async(payload_str))

# ── MQTT setup ────────────────────────────────────────────
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected with code {rc}")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    process_message(msg.payload.decode())

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
mqtt_client.loop_start()

# ── REST endpoints ────────────────────────────────────────
@app.get("/devices")
def get_devices():
    return [
        {"did": did, **info}
        for did, info in devices.items()
    ]

@app.post("/register")
async def register_device(req: RegisterRequest):
    try:
        did = generate_did(req.mac)
        pda = await register_device_onchain(
            did=did,
            public_key_hex=req.mac.replace(":", ""),
            device_type=req.device_type,
            location=req.location
        )
        devices[did] = {
            "name": req.name,
            "type": req.device_type,
            "location": req.location,
            "status": "pending",
            "pda": pda
        }
        print(f"[REGISTERED] {req.name} → {did}")
        return {"success": True, "did": did, "pda": pda, "status": "pending"}
    except Exception as e:
        print(f"[ERROR] Registration failed: {e}")
        return {"success": False, "error": str(e)}

@app.post("/revoke/{did}")
def revoke_device(did: str):
    if did in devices:
        devices[did]["status"] = "revoked"
        print(f"[REVOKED] {did}")
        return {"message": f"Device {did} revoked"}
    return {"error": "Device not found"}

@app.post("/verify/{did}")
def verify_device(did: str):
    if did in devices:
        devices[did]["status"] = "verified"
        print(f"[VERIFIED] {did}")
        return {"message": f"Device {did} verified"}
    return {"error": "Device not found"}

@app.post("/verify-onchain/{did}")
async def verify_device_onchain_endpoint(did: str):
    try:
        await verify_device_onchain(did)
        if did in devices:
            devices[did]["status"] = "verified"
        print(f"[VERIFIED ON-CHAIN] {did}")
        return {"success": True, "did": did, "status": "verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/revoke-onchain/{did}")
async def revoke_device_onchain_endpoint(did: str):
    try:
        await revoke_device_onchain(did)
        if did in devices:
            devices[did]["status"] = "revoked"
        print(f"[REVOKED ON-CHAIN] {did}")
        return {"success": True, "did": did, "status": "revoked"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
def health():
    return {"status": "ok", "program_id": PROGRAM_ID, "rpc": SOLANA_RPC}

# ── WebSocket ─────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    print(f"[WS] Client connected. Total: {len(ws_clients)}")
    try:
        while True:
            await websocket.receive_text()
    except:
        ws_clients.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(ws_clients)}")