/**
 * baileys-sender/setup/get-channel-jid.js
 * ─────────────────────────────────────────
 * ONE-TIME script — Run this to extract your Channel JID.
 *
 * Uses your saved Supabase session (from first-time-setup.js)
 * to connect to WhatsApp and query the real JID for your channel.
 *
 * Usage:
 *   cd "E:\AI NEWS CHANNEL\baileys-sender"
 *   node setup/get-channel-jid.js
 */

import 'dotenv/config'
import makeWASocket, { fetchLatestBaileysVersion } from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from '../auth/supabaseAuthState.js'
import pino from 'pino'

// ── Your channel invite code (part after /channel/ in the share link)
// https://whatsapp.com/channel/0029Vb7saIyBfxo16VOMZj3x
const INVITE_CODE = '0029Vb7saIyBfxo16VOMZj3x'

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY)
const logger = pino({ level: 'silent' })

async function getChannelJid() {
  console.log('\n🔍 Connecting to WhatsApp to retrieve Channel JID...\n')

  const { state, saveCreds } = await useSupabaseAuthState(supabase)
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: ['NewsBot', 'Chrome', '122.0.0.0'],
    connectTimeoutMs: 30_000,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection }) => {
    if (connection !== 'open') return

    console.log('✅ Connected!\n')

    // ── Method 1: query channel directly from invite code
    try {
      const info = await sock.getNewsletterInfoFromInvite(INVITE_CODE)
      printJid(info)
      return
    } catch { /* try next */ }

    // ── Method 2: list all newsletters this account follows/owns
    try {
      const list = await sock.getJoinedNewsletters()
      if (list?.length) {
        console.log(`Found ${list.length} channel(s):\n`)
        list.forEach((ch, i) => {
          console.log(`Channel ${i + 1}: ${ch.name || ch.subject || 'Unnamed'}`)
          console.log(`JID:       ${ch.id}`)
          console.log('─'.repeat(50))
        })
        done()
        return
      }
    } catch { /* try next */ }

    // ── Method 3: newsletterSubscriptionsGet
    try {
      const res = await sock.newsletterSubscriptionsGet()
      const list = Array.isArray(res) ? res : (res?.newsletters || [])
      if (list?.length) {
        list.forEach((ch, i) => {
          console.log(`Channel ${i + 1}: ${ch.name || 'Unnamed'}`)
          console.log(`JID:       ${ch.id}`)
          console.log('─'.repeat(50))
        })
        done()
        return
      }
    } catch { /* fall through */ }

    // ── Fallback: manual instructions
    console.log('⚠️  Could not auto-retrieve JID via Baileys API.')
    console.log('\n📋 Your JID can be constructed from your invite link:')
    console.log(`   Invite link: https://whatsapp.com/channel/${INVITE_CODE}`)
    console.log('\n   Run this alternative command instead:')
    console.log('   node setup/decode-jid.js\n')
    process.exit(0)
  })
}

function printJid(info) {
  console.log('╔══════════════════════════════════════════════╗')
  console.log('║         YOUR WHATSAPP CHANNEL JID            ║')
  console.log('╠══════════════════════════════════════════════╣')
  console.log(`║  Name: ${(info.name || 'AI News').padEnd(38)}║`)
  console.log(`║  JID:  ${(info.id || '').padEnd(38)}║`)
  console.log('╚══════════════════════════════════════════════╝')
  console.log('\n👆 Copy the JID above and add it to GitHub Secrets as WHATSAPP_CHANNEL_JID\n')
  done()
}

function done() {
  setTimeout(() => process.exit(0), 1000)
}

getChannelJid().catch(err => {
  console.error('❌ Error:', err.message)
  process.exit(1)
})
