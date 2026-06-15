/**
 * baileys-sender/setup/first-time-setup.js
 * ─────────────────────────────────────────
 * ONE-TIME SCRIPT — Run this locally (not in GitHub Actions).
 *
 * What it does:
 *   1. Connects to WhatsApp via Baileys (shows QR code in terminal)
 *   2. On successful pair, lists all WhatsApp Channels you manage
 *   3. Saves session credentials to Supabase whatsapp_auth table
 *   4. Exits cleanly
 *
 * After running this script:
 *   - Copy the Channel JID printed to terminal
 *   - Add it to GitHub Secrets as WHATSAPP_CHANNEL_JID
 *   - Verify whatsapp_auth table in Supabase has rows
 *   - Phase 8 is complete — proceed to Phase 9 (sender.js)
 *
 * Usage:
 *   cd "E:\AI NEWS CHANNEL\baileys-sender"
 *   node setup/first-time-setup.js
 */

import 'dotenv/config'
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from '../auth/supabaseAuthState.js'
import qrcode from 'qrcode-terminal'
import pino from 'pino'
import { Boom } from '@hapi/boom'

// ─── Validate environment ─────────────────────────────────────────────────────
const SUPABASE_URL = process.env.SUPABASE_URL
const SUPABASE_KEY = process.env.SUPABASE_KEY

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('❌ ERROR: SUPABASE_URL and SUPABASE_KEY must be set.')
  console.error('   Create baileys-sender/.env with these values.')
  console.error('   See baileys-sender/.env.example for format.')
  process.exit(1)
}

// ─── Supabase client ──────────────────────────────────────────────────────────
const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

// ─── Silent logger (suppress Baileys internal noise) ─────────────────────────
const logger = pino({ level: 'silent' })

// ─── Main connection logic ────────────────────────────────────────────────────
async function startSetup() {
  console.log('\n🔧 NewsBot — First-Time WhatsApp Setup')
  console.log('══════════════════════════════════════')
  console.log('Loading session from Supabase...\n')

  const { state, saveCreds } = await useSupabaseAuthState(supabase)
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,       // We render it ourselves for better formatting
    browser: ['NewsBot', 'Chrome', '122.0.0.0'],
    connectTimeoutMs: 60_000,
    keepAliveIntervalMs: 30_000,
  })

  // Save credentials whenever Baileys updates them
  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection, qr, lastDisconnect }) => {

    // ── QR code appeared ───────────────────────────────────────────────────
    if (qr) {
      console.log('╔══════════════════════════════════════════════╗')
      console.log('║        SCAN THIS QR CODE WITH WHATSAPP       ║')
      console.log('║                                              ║')
      console.log('║  WhatsApp → Settings → Linked Devices        ║')
      console.log('║               → Link a Device               ║')
      console.log('╚══════════════════════════════════════════════╝\n')
      qrcode.generate(qr, { small: true })
      console.log('\n⏳ Waiting for scan... (60 second timeout)\n')
    }

    // ── Connected ─────────────────────────────────────────────────────────
    if (connection === 'open') {
      console.log('\n✅ Connected to WhatsApp successfully!\n')

      // Save credentials immediately on connection
      await saveCreds()
      console.log('✅ Session saved to Supabase (whatsapp_auth table)\n')

      // Try to list WhatsApp Channels this account manages
      console.log('🔍 Looking for WhatsApp Channels you manage...\n')
      await listChannels(sock)

      console.log('\n══════════════════════════════════════════════')
      console.log('✅ Phase 8 Complete!')
      console.log('══════════════════════════════════════════════')
      console.log('\nNext steps:')
      console.log('  1. Copy your Channel JID from above')
      console.log('  2. Go to: GitHub → Your Repo → Settings → Secrets → Actions')
      console.log('  3. Update WHATSAPP_CHANNEL_JID with the real JID')
      console.log('  4. Verify Supabase → whatsapp_auth table has rows')
      console.log('  5. Proceed to Phase 9 (sender.js)\n')

      process.exit(0)
    }

    // ── Disconnected ──────────────────────────────────────────────────────
    if (connection === 'close') {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode
      const shouldReconnect = reason !== DisconnectReason.loggedOut

      console.log(`\n⚠️  Disconnected. Reason: ${reason}`)

      if (reason === DisconnectReason.loggedOut) {
        console.log('❌ Logged out — session cleared. Re-run this script to pair again.')
        process.exit(1)
      } else if (reason === 408 || reason === 503) {
        console.log('⏳ Timeout — QR code expired. Re-run this script to get a new QR.')
        process.exit(1)
      } else if (shouldReconnect) {
        console.log('🔄 Reconnecting...\n')
        startSetup()
      }
    }
  })
}

// ─── List channels helper ─────────────────────────────────────────────────────
async function listChannels(sock) {
  const methods = [
    // Try common Baileys newsletter methods in order
    ['getJoinedNewsletters',   () => sock.getJoinedNewsletters()],
    ['newsletterSubscriptionsGet', () => sock.newsletterSubscriptionsGet()],
  ]

  for (const [name, fn] of methods) {
    try {
      const result = await fn()
      const channels = Array.isArray(result) ? result : result?.newsletters || []

      if (channels.length === 0) {
        console.log('ℹ️  No WhatsApp Channels found for this account.')
        break
      }

      console.log(`Found ${channels.length} channel(s):\n`)
      channels.forEach((ch, i) => {
        const id   = ch.id   || ch.jid   || ch.newsletter_jid || 'unknown'
        const name = ch.name || ch.subject || ch.title || 'Unnamed'
        console.log(`  Channel ${i + 1}: ${name}`)
        console.log(`  JID:     ${id}`)
        console.log(`  ──────────────────────────────────────────────`)
      })

      console.log('\n👆 Copy the JID above and save it as GitHub Secret WHATSAPP_CHANNEL_JID')
      return
    } catch {
      // Method not available in this Baileys version — try next
    }
  }

  // If no method worked, give manual instructions
  console.log('ℹ️  Could not auto-list channels (Baileys API varies by version).')
  console.log('\n📋 To find your Channel JID manually:')
  console.log('   1. Open WhatsApp on your phone')
  console.log('   2. Go to your Channel')
  console.log('   3. Tap the channel name → Share → Copy Link')
  console.log('   4. The link looks like: https://whatsapp.com/channel/XXXX')
  console.log('   5. Your JID format: 120363XXXXXXXXXX@newsletter')
  console.log('\n   Or check the newsbot logs — after first send, JID will be printed.')
}

// ─── Start ────────────────────────────────────────────────────────────────────
startSetup().catch((err) => {
  console.error('❌ Fatal error:', err)
  process.exit(1)
})
