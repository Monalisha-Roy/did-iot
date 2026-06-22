use anchor_lang::prelude::*;

declare_id!("8NXipim1BqhH9rKdsqHsYj7dh1YLLjYrt9vpkxL8rJEN");

#[program]
pub mod did_registry {
    use super::*;

    // Register a new IoT device with a DID and public key
    pub fn register_device(
        ctx: Context<RegisterDevice>,
        did: String,
        name: String,
        public_key_hex: String,
        device_type: String,
        location: String,
    ) -> Result<()> {
        let device = &mut ctx.accounts.device;
        device.owner = ctx.accounts.authority.key();
        device.did = did;
        device.name = name;
        device.public_key_hex = public_key_hex;
        device.device_type = device_type;
        device.location = location;
        device.status = DeviceStatus::Pending;
        device.registered_at = Clock::get()?.unix_timestamp;
        device.bump = ctx.bumps.device;
        msg!("Device registered: {}", device.did);
        Ok(())
    }

    // Admin verifies a device — issues the VC
    pub fn verify_device(ctx: Context<UpdateDevice>) -> Result<()> {
        let device = &mut ctx.accounts.device;
        require!(
            device.owner == ctx.accounts.authority.key(),
            DIDError::Unauthorized
        );
        device.status = DeviceStatus::Verified;
        msg!("Device verified: {}", device.did);
        Ok(())
    }

    // Admin revokes a device — blocks all its data
    pub fn revoke_device(ctx: Context<UpdateDevice>) -> Result<()> {
        let device = &mut ctx.accounts.device;
        require!(
            device.owner == ctx.accounts.authority.key(),
            DIDError::Unauthorized
        );
        device.status = DeviceStatus::Revoked;
        msg!("Device revoked: {}", device.did);
        Ok(())
    }

    // Store IPFS CID on-chain after verified data is uploaded to Pinata
    pub fn store_data_cid(
        ctx: Context<StoreData>,
        cid: String,
        timestamp: i64,
    ) -> Result<()> {
        let record = &mut ctx.accounts.data_record;
        record.device = ctx.accounts.device.key();
        record.did = ctx.accounts.device.did.clone();
        record.cid = cid;
        record.timestamp = timestamp;
        record.bump = ctx.bumps.data_record;
        msg!("Data CID stored: {}", record.cid);
        Ok(())
    }
}

// ── Accounts ──────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(did: String)]
pub struct RegisterDevice<'info> {
    #[account(
        init,
        payer = authority,
        space = DeviceAccount::LEN,
        seeds = [b"device", &did.as_bytes()[..did.as_bytes().len().min(32)]],
        bump
    )]
    pub device: Account<'info, DeviceAccount>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateDevice<'info> {
    #[account(mut)]
    pub device: Account<'info, DeviceAccount>,
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(cid: String, timestamp: i64)]
pub struct StoreData<'info> {
    #[account(
        init,
        payer = authority,
        space = DataRecord::LEN,
        seeds = [b"data", device.key().as_ref(), &timestamp.to_le_bytes()],
        bump
    )]
    pub data_record: Account<'info, DataRecord>,
    #[account(mut)]
    pub device: Account<'info, DeviceAccount>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

// ── State ─────────────────────────────────────────────────

#[account]
pub struct DeviceAccount {
    pub owner: Pubkey,
    pub did: String,
    pub name: String,
    pub public_key_hex: String,
    pub device_type: String,
    pub location: String,
    pub status: DeviceStatus,
    pub registered_at: i64,
    pub bump: u8,
}

impl DeviceAccount {
    pub const LEN: usize = 8       // discriminator
        + 32                        // owner pubkey
        + 4 + 64                    // did string
        + 4 + 64                    // name string
        + 4 + 128                   // public_key_hex
        + 4 + 32                    // device_type
        + 4 + 64                    // location
        + 1                         // status enum
        + 8                         // registered_at
        + 1;                        // bump
}

#[account]
pub struct DataRecord {
    pub device: Pubkey,
    pub did: String,
    pub cid: String,
    pub timestamp: i64,
    pub bump: u8,
}

impl DataRecord {
    pub const LEN: usize = 8       // discriminator
        + 32                        // device pubkey
        + 4 + 64                    // did
        + 4 + 64                    // cid (IPFS CIDs ~46 chars, padded)
        + 8                         // timestamp
        + 1;                        // bump
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq)]
pub enum DeviceStatus {
    Pending,
    Verified,
    Revoked,
}

// ── Errors ────────────────────────────────────────────────

#[error_code]
pub enum DIDError {
    #[msg("You are not authorized to perform this action")]
    Unauthorized,
}