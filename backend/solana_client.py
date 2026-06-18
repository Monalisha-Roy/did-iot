import json
import os
import struct
import hashlib
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

PROGRAM_ID = "B3gYy9xnAUiU3qW9seVVUgZ6kSWzz7ePibCSXbsJK9eq"
RPC_URL = "https://api.devnet.solana.com"
KEYPAIR_PATH = os.path.expanduser("~/.config/solana/id.json")
SYS_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

def load_keypair():
    with open(KEYPAIR_PATH) as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

def generate_did(mac: str) -> str:
    clean = mac.replace(":", "").replace("-", "").lower()
    return f"did:sol:{clean}"

def get_program_id():
    return Pubkey.from_string(PROGRAM_ID)

def get_device_pda(did: str):
    program_id = get_program_id()
    did_bytes = did.encode()
    pda, bump = Pubkey.find_program_address(
        [b"device", did_bytes],
        program_id
    )
    return pda, bump

def encode_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded

def discriminator(name: str) -> bytes:
    # Anchor discriminator = first 8 bytes of sha256("global:<name>")
    h = hashlib.sha256(f"global:{name}".encode()).digest()
    return h[:8]

async def send_instruction(ix: Instruction, keypair: Keypair):
    client = AsyncClient(RPC_URL)
    try:
        blockhash_resp = await client.get_latest_blockhash()
        blockhash = blockhash_resp.value.blockhash

        msg = Message.new_with_blockhash(
            [ix],
            keypair.pubkey(),
            blockhash
        )
        tx = Transaction([keypair], msg, blockhash)
        resp = await client.send_transaction(tx)
        print(f"[TX] Sent: {resp.value}")

        # Wait for confirmation
        await client.confirm_transaction(resp.value, Confirmed)
        print(f"[TX] Confirmed!")
        return str(resp.value)
    finally:
        await client.close()

async def register_device_onchain(did: str, public_key_hex: str, device_type: str, location: str):
    keypair = load_keypair()
    program_id = get_program_id()
    device_pda, _ = get_device_pda(did)

    # Build instruction data
    data = (
        discriminator("register_device") +
        encode_string(did) +
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

    data = discriminator("verify_device")

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

    data = discriminator("revoke_device")

    accounts = [
        AccountMeta(pubkey=device_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=False),
    ]

    ix = Instruction(program_id, data, accounts)
    await send_instruction(ix, keypair)