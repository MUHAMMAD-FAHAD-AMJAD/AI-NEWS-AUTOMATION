/**
 * baileys-sender/utils/antiBan.js
 * ─────────────────────────────────
 * Anti-ban utilities for WhatsApp Channel posting.
 *
 * WhatsApp aggressively bans accounts that post with bot-like patterns:
 *   - Instant sends (no human delay)
 *   - Always same browser fingerprint
 *   - No composing indicator before message
 *
 * These utilities simulate human behaviour to minimize ban risk.
 */

// ─── Basic helpers ────────────────────────────────────────────────────────────

/** Sleep for exactly `ms` milliseconds. */
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * Return a random integer between min and max (inclusive).
 * Used to randomize delays so timing patterns are not predictable.
 */
export const randomInt = (min, max) =>
  Math.floor(Math.random() * (max - min + 1)) + min

// ─── Human delay ─────────────────────────────────────────────────────────────

/**
 * humanDelay()
 * ─────────────
 * Wait 5–15 seconds before sending.
 *
 * A human who just opened WhatsApp and found an article to share
 * would take several seconds before actually sending the message.
 * This delay pattern avoids the "instant send = bot" signal.
 */
export async function humanDelay() {
  const delay = randomInt(5_000, 15_000)
  console.log(`[ANTI-BAN] Human delay: ${(delay / 1000).toFixed(1)}s before send...`)
  await sleep(delay)
}

// ─── Composing simulation ─────────────────────────────────────────────────────

/**
 * simulateComposing(sock, jid)
 * ─────────────────────────────
 * Briefly show "typing..." presence before sending.
 *
 * NOTE: WhatsApp Channels may not show composing indicators to subscribers,
 * but the presence update still travels through WA servers and looks more
 * like a real user session than a silent direct send.
 *
 * Sequence:
 *   1. Set presence to 'composing' (2–4 seconds)
 *   2. Set presence to 'paused'   (0.5–1.5 seconds)
 *   3. Send message (called by caller)
 */
export async function simulateComposing(sock, jid) {
  try {
    await sock.sendPresenceUpdate('composing', jid)
    await sleep(randomInt(2_000, 4_000))
    await sock.sendPresenceUpdate('paused', jid)
    await sleep(randomInt(500, 1_500))
  } catch {
    // Presence update errors are non-fatal — proceed with send
  }
}

// ─── Browser fingerprint rotation ─────────────────────────────────────────────

/**
 * BROWSERS
 * ─────────
 * Pool of Chrome versions used to rotate the Baileys browser fingerprint.
 * Using a single fixed version would look robotic; rotation mimics organic use.
 */
const BROWSERS = [
  ['Chrome', '120.0.0.0'],
  ['Chrome', '121.0.0.0'],
  ['Chrome', '122.0.0.0'],
  ['Chrome', '123.0.0.0'],
]

/**
 * getRandomBrowser()
 * ───────────────────
 * Pick a random browser version from the pool.
 * Returns [browserName, version] — pass directly to Baileys `browser` option.
 *
 * @returns {[string, string]}
 */
export function getRandomBrowser() {
  return BROWSERS[randomInt(0, BROWSERS.length - 1)]
}
