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
import https from 'https'
import http from 'http'
import pino from 'pino'
import { Boom } from '@hapi/boom'

// ─── Fallback image ───────────────────────────────────────────────────────────
// Used when the article's OG image fails to download (403, 429, timeout, etc.).
// Picsum Photos seeds are permanent — this URL always resolves to the same image.
// Swap this constant at any time to use your own branded placeholder.
const FALLBACK_IMAGE_URL = 'https://picsum.photos/seed/ainews/1200/630'

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

// ─── Image buffer downloader ──────────────────────────────────────────────────

/**
 * Download an image URL to a Buffer.
 * WhatsApp newsletter channels silently drop image+URL messages.
 * Sending a Buffer instead of { url } works correctly for newsletters.
 *
 * @param {string} imageUrl  HTTPS URL of the image to fetch
 * @param {number} timeoutMs Timeout in milliseconds (default 15s)
 * @returns {Promise<Buffer|null>} Image buffer, or null on any failure
 */
function downloadImageBuffer(imageUrl, timeoutMs = 15_000) {
  return new Promise((resolve) => {
    const protocol = imageUrl.startsWith('https') ? https : http
    const req = protocol.get(
      imageUrl,
      {
        timeout: timeoutMs,
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
          'Accept': 'image/*,*/*;q=0.8',
        },
      },
      (res) => {
        // Follow redirects (up to 3)
        if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
          console.log(`[IMAGE] Redirect ${res.statusCode} -> ${res.headers.location.slice(0, 60)}`)
          downloadImageBuffer(res.headers.location, timeoutMs).then(resolve)
          return
        }
        if (res.statusCode !== 200) {
          console.error(`[IMAGE] Download failed: HTTP ${res.statusCode}`)
          resolve(null)
          return
        }
        const chunks = []
        res.on('data', chunk => chunks.push(chunk))
        res.on('end', () => {
          const buf = Buffer.concat(chunks)
          console.log(`[IMAGE] Downloaded ${(buf.length / 1024).toFixed(1)} KB`)
          resolve(buf)
        })
        res.on('error', (e) => {
          console.error(`[IMAGE] Stream error: ${e.message}`)
          resolve(null)
        })
      }
    )
    req.on('timeout', () => {
      req.destroy()
      console.error('[IMAGE] Download timeout')
      resolve(null)
    })
    req.on('error', (e) => {
      console.error(`[IMAGE] Request error: ${e.message}`)
      resolve(null)
    })
  })
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
        // 3-tier image delivery strategy:
        //   Tier 1 — Article OG image: download to Buffer, send as
        //            { image: buffer, caption }. Buffer sends work for
        //            @newsletter JIDs; { url } sends are silently dropped
        //            by WhatsApp's server for newsletter channels.
        //   Tier 2 — Fallback placeholder: if article image download fails
        //            (403, 429, timeout, etc.), download FALLBACK_IMAGE_URL
        //            to Buffer and send with the same caption. The channel
        //            always delivers a visual post — never degrades silently.
        //   Tier 3 — Text-only: only reached if BOTH image downloads fail.
        //            Guarantees the pipeline never hard-exits without sending.
        let result

        if (payload.has_image && payload.og_image_url) {
          // ── Tier 1: article OG image ──────────────────────────────────
          console.log('[IMAGE] Tier 1 — downloading article OG image...')
          const imgBuffer = await downloadImageBuffer(payload.og_image_url)

          if (imgBuffer && imgBuffer.length > 0) {
            console.log('[SEND] Tier 1 success — sending article image + caption.')
            result = await sock.sendMessage(CHANNEL_JID, {
              image:   imgBuffer,
              caption: payload.formatted_message,
            })
          } else {
            // ── Tier 2: generic placeholder image ────────────────────────
            console.log('[IMAGE] Tier 1 failed — trying Tier 2 placeholder image...')
            const fallbackBuffer = await downloadImageBuffer(FALLBACK_IMAGE_URL)

            if (fallbackBuffer && fallbackBuffer.length > 0) {
              console.log('[SEND] Tier 2 success — sending placeholder image + caption.')
              result = await sock.sendMessage(CHANNEL_JID, {
                image:   fallbackBuffer,
                caption: payload.formatted_message,
              })
            } else {
              // ── Tier 3: text-only last resort ──────────────────────────
              console.log('[SEND] Tier 2 failed — falling back to text-only (Tier 3).')
              result = await sock.sendMessage(CHANNEL_JID, {
                text: payload.formatted_message,
              })
            }
          }
        } else {
          // No image in payload — go straight to Tier 3
          console.log('[SEND] No image in payload — sending text only.')
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
