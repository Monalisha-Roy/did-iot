import json
import os
import struct
import hashlib
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
import base64
import base58

PROGRAM_ID = os.getenv("PROGRAM_ID", "8NXipim1BqhH9rKdsqHsYj7dh1YLLjYrt9vpkxL8rJEN")
RPC_URL = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
KEYPAIR_PATH = os.path.expanduser("~/.config/solana/id.json")
SYS_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

IDL_PATH = os.path.join(os.path.dirname(__file__), "did_registry.json")
with open(IDL_PATH) as f:
    IDL = json.load(f)

DISCRIMINATORS = {
    ix["name"]: bytes(ix["discriminator"])
    for ix in IDL["instructions"]
}

ACCOUNT_DISCRIMINATORS = {
    acc["name"]: bytes(acc["discriminator"])
    for acc in IDL["accounts"]
}

def load_keypair():
    with open(KEYPAIR_PATH) as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

def generate_did(public_key_hex: str) -> str:
    return f"did:sol:{public_key_hex}"

def get_program_id():
    return Pubkey.from_string(PROGRAM_ID)

def get_device_pda(did: str):
    program_id = get_program_id()
    did_bytes = did.encode()
    seed = did_bytes[:min(len(did_bytes), 32)]
    pda, bump = Pubkey.find_program_address(
        [b"device", seed],
        program_id
    )
    return pda, bump

def encode_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded

async def send_instruction(ix: Instruction, keypair: Keypair):
    client = AsyncClient(RPC_URL)
    try:
        blockhash_resp = await client.get_latest_blockhash()
        blockhash = blockhash_resp.value.blockhash
        msg = Message.new_with_blockhash([ix], keypair.pubkey(), blockhash)
        tx = Transaction([keypair], msg, blockhash)
        resp = await client.send_transaction(tx)
        print(f"[TX] Sent: {resp.value}")
        await client.confirm_transaction(resp.value, Confirmed)
        print(f"[TX] Confirmed!")
        return str(resp.value)
    finally:
        await client.close()

async def register_device_onchain(did: str, public_key_hex: str, device_type: str, location: str):
    keypair = load_keypair()
    program_id = get_program_id()
    device_pda, _ = get_device_pda(did)

    data = (
        DISCRIMINATORS["register_device"] +
        encode_string(did) +
        encode_string("")  +          # name field (empty)
        encode_string(public_key_hex) +
        encode_string(device_type) +
        encode_string(location)
    )

    accounts = [
        AccountMeta(pubkey=device_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM, is_signer=False, is_writable=False),
    ]

    ix = Instruction(program_id, data, accounts)
    await send_instruction(ix, keypair)
    return str(device_pda)

async def verify_device_onchain(did: str):
    keypair = load_keypair()
    program_id = get_program_id()
    device_pda, _ = get_device_pda(did)

    data = DISCRIMINATORS["verify_device"]

    accounts = [
        AccountMeta(pubkey=device_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=False),
    ]

    ix = Instruction(program_id, data, accounts)
    await send_instruction(ix, keypair)

async def revoke_device_onchain(did: str):
    keypair = load_keypair()
    program_id = get_program_id()
    device_pda, _ = get_device_pda(did)

    data = DISCRIMINATORS["revoke_device"]

    accounts = [
        AccountMeta(pubkey=device_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=False),
    ]

    ix = Instruction(program_id, data, accounts)
    await send_instruction(ix, keypair)

def decode_device_account(data: bytes) -> dict:
    try:
        offset = 8  # discriminator
        offset += 32  # owner pubkey

        did_len = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        did_str = data[offset:offset+did_len].decode()
        offset += did_len

        # skip name field
        name_len = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        offset += name_len

        pk_len = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        public_key_hex = data[offset:offset+pk_len].decode()
        offset += pk_len

        dt_len = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        device_type = data[offset:offset+dt_len].decode()
        offset += dt_len

        loc_len = int.from_bytes(data[offset:offset+4], 'little')
        offset += 4
        location = data[offset:offset+loc_len].decode()
        offset += loc_len

        status_byte = data[offset]
        status = ["pending", "verified", "revoked"][status_byte]
        offset += 1

        registered_at = int.from_bytes(data[offset:offset+8], 'little')

        return {
            "did": did_str,
            "public_key_hex": public_key_hex,
            "type": device_type,
            "location": location,
            "status": status,
            "registered_at": registered_at
        }
    except Exception as e:
        print(f"[DECODE ERROR] {e}")
        return None

async def get_device_onchain(did: str) -> dict | None:
    client = AsyncClient(RPC_URL)
    try:
        device_pda, _ = get_device_pda(did)
        resp = await client.get_account_info(device_pda, encoding="base64")
        if resp.value is None:
            return None
        raw = resp.value.data
        if isinstance(raw, list):
            data = base64.b64decode(raw[0])
        else:
            data = bytes(raw)
        return decode_device_account(data)
    finally:
        await client.close()

async def get_all_devices_onchain() -> list[dict]:
    client = AsyncClient(RPC_URL)
    try:
        program_id = get_program_id()
        device_disc = ACCOUNT_DISCRIMINATORS["DeviceAccount"]

        from solana.rpc.types import MemcmpOpts
        filters = [
            MemcmpOpts(offset=0, bytes=base58.b58encode(device_disc).decode())
        ]

        resp = await client.get_program_accounts(
            program_id,
            encoding="base64",
            filters=filters
        )

        print(f"[DEBUG] Accounts found: {len(resp.value)}")

        devices = []
        for account in resp.value:
            try:
                raw = account.account.data
                if isinstance(raw, list):
                    data = base64.b64decode(raw[0])
                else:
                    data = bytes(raw)
                decoded = decode_device_account(data)
                if decoded:
                    decoded["pda"] = str(account.pubkey)
                    devices.append(decoded)
            except Exception as e:
                print(f"[SKIP] {e}")
                continue

        return devices
    finally:
        await client.close()