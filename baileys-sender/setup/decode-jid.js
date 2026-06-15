/**
 * baileys-sender/setup/decode-jid.js
 * Uses newsletterMetadata('invite', code) — the correct Baileys API
 * to get your Channel JID from the invite link.
 *
 * Usage:
 *   node setup/decode-jid.js
 */

import 'dotenv/config'
import makeWASocket, { fetchLatestBaileysVersion } from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from '../auth/supabaseAuthState.js'
import pino from 'pino'

const INVITE_CODE = '0029Vb7saIyBfxo16VOMZj3x'

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY)

async function run() {
  console.log('\n🔍 Fetching Channel JID from invite code...\n')

  const { state, saveCreds } = await useSupabaseAuthState(supabase)
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
    browser: ['NewsBot', 'Chrome', '122.0.0.0'],
    connectTimeoutMs: 30_000,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection }) => {
    if (connection !== 'open') return
    console.log('✅ Connected to WhatsApp\n')

    // Try all known Baileys newsletter query methods
    const attempts = [
      // Correct Baileys API: newsletterMetadata(type, identifier)
      async () => sock.newsletterMetadata('invite', INVITE_CODE),
      async () => sock.newsletterMetadata('jid',    INVITE_CODE),
      // Some versions use different casing
      async () => sock.getNewsLetterInfoFromInvite?.(INVITE_CODE),
      async () => sock.queryNewsletterFromInvite?.(INVITE_CODE),
    ]

    for (const attempt of attempts) {
      try {
        const info = await attempt()
        if (info?.id) {
          console.log('╔══════════════════════════════════════════════╗')
          console.log('║         YOUR WHATSAPP CHANNEL JID            ║')
          console.log('╠══════════════════════════════════════════════╣')
          console.log(`║  Name: ${String(info.name || 'AI News').padEnd(38)}║`)
          console.log(`║  JID:  ${String(info.id).padEnd(38)}║`)
          console.log('╚══════════════════════════════════════════════╝')
          console.log('\n✅ Copy the JID above → add to GitHub Secrets as WHATSAPP_CHANNEL_JID\n')
          setTimeout(() => process.exit(0), 500)
          return
        }
      } catch { /* try next */ }
    }

    // If all methods fail, log available sock methods containing 'newsletter'
    console.log('⚠️  All auto-methods failed. Checking available Baileys methods...\n')
    const methods = Object.keys(sock).filter(k =>
      typeof sock[k] === 'function' && k.toLowerCase().includes('news')
    )
    if (methods.length) {
      console.log('Available newsletter methods in your Baileys version:')
      methods.forEach(m => console.log(`  - sock.${m}`))
    } else {
      console.log('No newsletter methods found in this Baileys build.')
    }
    console.log('\nAll sock methods:')
    Object.keys(sock)
      .filter(k => typeof sock[k] === 'function')
      .forEach(m => console.log(`  sock.${m}`))
    process.exit(0)
  })
}

run().catch(err => { console.error('Error:', err.message); process.exit(1) })
