/**
 * baileys-sender/sender.js
 * ─────────────────────────
 * WhatsApp Channel sender — Phase 9.
 *
 * Called by GitHub Actions after Python orchestrator writes payload.json.
 * Reads the article payload, connects to WhatsApp using the Supabase-stored
 * session, posts the message (with or without OG image), logs the result
 * to Supabase, and exits.
 *
 * Environment variables (injected by GitHub Actions):
 *   SUPABASE_URL            — Supabase project URL
 *   SUPABASE_KEY            — Supabase anon key
 *   WHATSAPP_CHANNEL_JID    — e.g. 120363428273470750@newsletter
 *   ARTICLE_PAYLOAD_PATH    — path to payload.json written by Python
 *
 * Exit codes:
 *   0 — Message sent successfully
 *   1 — Fatal error (session expired, send failed, payload missing)
 */

import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from './auth/supabaseAuthState.js'
import { humanDelay, simulateComposing, getRandomBrowser } from './utils/antiBan.js'
import { readFileSync, existsSync } from 'fs'
import pino from 'pino'
import { Boom } from '@hapi/boom'

// ─── Validate environment ─────────────────────────────────────────────────────

const SUPABASE_URL  = process.env.SUPABASE_URL
const SUPABASE_KEY  = process.env.SUPABASE_KEY
const CHANNEL_JID   = process.env.WHATSAPP_CHANNEL_JID
const PAYLOAD_PATH  = process.env.ARTICLE_PAYLOAD_PATH || '/tmp/article_payload.json'

const missing = []
if (!SUPABASE_URL)  missing.push('SUPABASE_URL')
if (!SUPABASE_KEY)  missing.push('SUPABASE_KEY')
if (!CHANNEL_JID)   missing.push('WHATSAPP_CHANNEL_JID')

if (missing.length) {
  console.error(`[SENDER] Missing required env vars: ${missing.join(', ')}`)
  process.exit(1)
}

if (!existsSync(PAYLOAD_PATH)) {
  console.error(`[SENDER] Payload file not found: ${PAYLOAD_PATH}`)
  process.exit(1)
}

// ─── Load payload ─────────────────────────────────────────────────────────────

let payload
try {
  payload = JSON.parse(readFileSync(PAYLOAD_PATH, 'utf8'))
} catch (err) {
  console.error(`[SENDER] Failed to parse payload JSON: ${err.message}`)
  process.exit(1)
}

console.log(`[SENDER] Payload loaded — article_hash: ${payload.article_hash}`)
console.log(`[SENDER] has_image: ${payload.has_image}`)
console.log(`[DEBUG] Sending to JID: ${CHANNEL_JID}`)
console.log(`[DEBUG] Message preview: ${payload.formatted_message?.substring(0, 80)}`)

// ─── Supabase client ──────────────────────────────────────────────────────────

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

// ─── Supabase helpers ─────────────────────────────────────────────────────────

async function markPosted(msgId) {
  await supabase
    .from('articles')
    .update({ status: 'POSTED', posted_at: new Date().toISOString() })
    .eq('hash', payload.article_hash)

  await supabase
    .from('post_log')
    .insert({
      article_hash:     payload.article_hash,
      status:           'success',
      whatsapp_msg_id:  msgId,
      had_image:        payload.has_image ?? false,
    })

  console.log('[DB] Article marked POSTED, post_log row inserted.')
}

async function markFailed(err) {
  await supabase
    .from('articles')
    .update({ status: 'FAILED' })
    .eq('hash', payload.article_hash)

  await supabase
    .from('post_log')
    .insert({
      article_hash:  payload.article_hash,
      status:        'failed',
      had_image:     payload.has_image ?? false,
      error_detail:  err.message?.slice(0, 500) ?? 'unknown error',
    })

  await supabase
    .from('error_log')
    .insert({
      component:     'whatsapp',
      provider:      'baileys',
      error_type:    err.constructor?.name ?? 'Error',
      error_message: err.message?.slice(0, 1000) ?? 'unknown',
      article_hash:  payload.article_hash,
    })

  console.error('[DB] Article marked FAILED, error logged.')
}

// ─── Main send flow ───────────────────────────────────────────────────────────

async function sendArticle() {
  console.log('[SENDER] Loading session from Supabase...')

  const { state, saveCreds } = await useSupabaseAuthState(supabase)
  const { version } = await fetchLatestBaileysVersion()
  const browser = getRandomBrowser()

  const sock = makeWASocket({
    version,
    auth:                         state,
    logger:                       pino({ level: 'silent' }),
    browser:                      ['NewsBot', browser[0], browser[1]],
    generateHighQualityLinkPreview: false,
    connectTimeoutMs:             30_000,
    keepAliveIntervalMs:          15_000,
  })

  sock.ev.on('creds.update', saveCreds)

  // Safety timeout — if no connection within 90s, abort
  const timeout = setTimeout(async () => {
    console.error('[TIMEOUT] Could not connect to WhatsApp within 90 seconds.')
    await markFailed(new Error('Connection timeout after 90s'))
    process.exit(1)
  }, 90_000)

  let sent = false
  let retries = 0
  const MAX_RETRIES = 2

  sock.ev.on('connection.update', async ({ connection, qr, lastDisconnect }) => {

    // ── QR needed → session expired ────────────────────────────────────────
    if (qr) {
      clearTimeout(timeout)
      console.error('[SENDER] Session expired — QR code required. Re-run first-time-setup.js.')
      await markFailed(new Error('WhatsApp session expired — QR re-pair required'))
      process.exit(1)
    }

    // ── Connected — execute send ───────────────────────────────────────────
    if (connection === 'open' && !sent) {
      sent = true
      clearTimeout(timeout)
      console.log(`[SENDER] Connected to WhatsApp. Browser: ${browser[0]} ${browser[1]}`)

      try {
        // Anti-ban: short delay for Channel posts (2-4s)
        // Channels are newsletters — shorter delay is safe vs personal chats
        const delay = 2000 + Math.floor(Math.random() * 2000)
        console.log(`[ANTI-BAN] Channel delay: ${(delay/1000).toFixed(1)}s...`)
        await new Promise(r => setTimeout(r, delay))

        // Anti-ban: simulate typing
        await simulateComposing(sock, CHANNEL_JID)

        // ── Send message ─────────────────────────────────────────────────
        // NOTE: WhatsApp newsletter channels (@newsletter JID) silently drop
        // image+caption messages sent via the standard sendMessage() API.
        // Baileys returns a success message ID but the post never appears.
        // Text-only is confirmed working for @newsletter channels.
        // Image support for newsletters requires a different Baileys API path
        // that varies by version and is not stable in CI environments.
        let result
        const isNewsletterJid = CHANNEL_JID.endsWith('@newsletter')

        if (payload.has_image && payload.og_image_url && !isNewsletterJid) {
          console.log('[SEND] Sending image + caption...')
          result = await sock.sendMessage(CHANNEL_JID, {
            image:   { url: payload.og_image_url },
            caption: payload.formatted_message,
          })
        } else {
          if (isNewsletterJid && payload.has_image) {
            console.log('[SEND] Newsletter channel — skipping image (would be silently dropped). Sending text only.')
          } else {
            console.log('[SEND] Sending text only (no OG image)...')
          }
          result = await sock.sendMessage(CHANNEL_JID, {
            text: payload.formatted_message,
          })
        }

        const msgId = result?.key?.id ?? null
        console.log(`[SEND] ✅ Success! Message ID: ${msgId}`)
        console.log(`[DEBUG] Sent to JID: ${CHANNEL_JID}`)

        // Persist success to Supabase
        await markPosted(msgId)

        // Save updated session keys
        await saveCreds()
        console.log('[SENDER] Session updated. Done.')
        process.exit(0)

      } catch (err) {
        console.error(`[SEND] ❌ Failed: ${err.message}`)
        await markFailed(err)
        process.exit(1)
      }
    }

    // ── Disconnected ──────────────────────────────────────────────────────
    if (connection === 'close') {
      const code = new Boom(lastDisconnect?.error)?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        clearTimeout(timeout)
        console.error('[SENDER] Logged out — session invalid.')
        await markFailed(new Error('WhatsApp logged out — session invalid'))
        process.exit(1)
      }
      // 408 = connection reset (common during heavy key writes)
      // Retry automatically up to MAX_RETRIES times
      if (!sent && retries < MAX_RETRIES) {
        retries++
        console.log(`[SENDER] Disconnected (code ${code}) — retry ${retries}/${MAX_RETRIES}...`)
        setTimeout(() => sendArticle(), 3000)
      } else if (!sent) {
        clearTimeout(timeout)
        console.error(`[SENDER] Max retries reached. Giving up.`)
        await markFailed(new Error(`WhatsApp disconnected after ${MAX_RETRIES} retries (code ${code})`))
        process.exit(1)
      }
    }
  })
}

// ─── Entry point ──────────────────────────────────────────────────────────────
sendArticle().catch(async (err) => {
  console.error('[SENDER] Fatal error:', err.message)
  try { await markFailed(err) } catch { /* ignore DB errors on fatal exit */ }
  process.exit(1)
})
