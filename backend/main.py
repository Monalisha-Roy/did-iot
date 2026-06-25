from pydantic import BaseModel
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
from solana_client import generate_did, register_device_onchain, verify_device_onchain, revoke_device_onchain, get_device_onchain, get_all_devices_onchain
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

ws_clients = []

class RegisterRequest(BaseModel):
    device_type: str
    location: str
    public_key: str

async def broadcast(data: dict):
    for ws in ws_clients.copy():
        try:
            await ws.send_json(data)
        except:
            ws_clients.remove(ws)

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

async def process_message_async(payload_str: str):
    try:
        msg = json.loads(payload_str)

        if "payload" in msg:
            payload = msg["payload"]
        else:
            payload = msg

        did = payload.get("did")
        value = payload.get("value")
        unit = payload.get("unit", "")
        timestamp = int(time.time()) 

        # Fetch device status directly from Solana
        chain_data = await get_device_onchain(did)

        if chain_data is None:
            print(f"[REJECTED] DID not found on Solana: {did}")
            return

        if chain_data["status"] != "verified":
            print(f"[REJECTED] Device not verified on-chain: {did} (status: {chain_data['status']})")
            return

        pinata_payload = {
            "did": did,
            "device_type": chain_data["type"],
            "value": value,
            "unit": unit,
            "timestamp": timestamp,
            "location": chain_data["location"],
        }

        # Add extra fields if present
        if "pressure" in payload:
            pinata_payload["pressure"] = payload.get("pressure")
        if "humidity" in payload:
            pinata_payload["humidity"] = payload.get("humidity")
        cid = await upload_to_pinata(pinata_payload)

        packet = {
            "did": did,
            "device_name": did,  # add this line
            "device_type": chain_data["type"],
            "value": f"{value} {unit}".strip(),
            "timestamp": timestamp,
            "hash": hex(abs(hash(payload_str)))[:10],
            "status": "verified",
            "cid": cid,
            "ipfs_url": f"https://gateway.pinata.cloud/ipfs/{cid}" if cid else None,
        }

        if "pressure" in payload:
            packet["value"] = f"{value}°C / {payload.get('pressure')}hPa"

        print(f"[ACCEPTED] {did}: {packet['value']} | CID: {cid}")
        await broadcast(packet)

    except Exception as e:
        print(f"[ERROR] {e}")

def process_message(payload_str: str):
    asyncio.run(process_message_async(payload_str))

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

@app.get("/devices")
async def get_devices():
    try:
        return await get_all_devices_onchain()
    except Exception as e:
        print(f"[ERROR] get_devices: {e}")
        return []

@app.post("/register")
async def register_device(req: RegisterRequest):
    try:
        did = f"did:sol:{req.public_key}"
        pda = await register_device_onchain(
            did=did,
            public_key_hex=req.public_key,
            device_type=req.device_type,
            location=req.location
        )
        print(f"[REGISTERED] {did}")
        return {"success": True, "did": did, "pda": pda, "status": "pending"}
    except Exception as e:
        print(f"[ERROR] Registration failed: {e}")
        return {"success": False, "error": str(e)}

@app.post("/verify-onchain/{did}")
async def verify_device_onchain_endpoint(did: str):
    try:
        await verify_device_onchain(did)
        print(f"[VERIFIED ON-CHAIN] {did}")
        return {"success": True, "did": did, "status": "verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/revoke-onchain/{did}")
async def revoke_device_onchain_endpoint(did: str):
    try:
        await revoke_device_onchain(did)
        print(f"[REVOKED ON-CHAIN] {did}")
        return {"success": True, "did": did, "status": "revoked"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
def health():
    return {"status": "ok", "program_id": PROGRAM_ID, "rpc": SOLANA_RPC}

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

@app.get("/packet-count")
async def get_packet_count():
    headers = {
        "Authorization": f"Bearer {PINATA_JWT}",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.pinata.cloud/data/pinList?status=pinned&metadata[name]=iot-data",
            headers=headers,
            timeout=15,
        )
        result = response.json()
        count = result.get("count", 0)
        return {"count": count}