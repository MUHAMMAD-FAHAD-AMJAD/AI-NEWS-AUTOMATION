/**
 * baileys-sender/auth/supabaseAuthState.js
 * ─────────────────────────────────────────
 * Custom Baileys auth state backed by Supabase JSONB.
 *
 * Replaces the standard useMultiFileAuthState() (which writes to disk)
 * with a cloud-persistent equivalent suited for ephemeral GitHub Actions
 * runners that have no persistent local storage between runs.
 *
 * Schema (from 05-BACKEND-SCHEMA.md §TABLE 3):
 *   CREATE TABLE whatsapp_auth (
 *     key        TEXT PRIMARY KEY,
 *     value      JSONB NOT NULL,
 *     updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
 *   );
 *
 * How Baileys uses this:
 *   - creds              → main credentials (registered phone, identity key, etc.)
 *   - app-state-sync-key-{id}  → Signal app-state keys
 *   - session-{id}             → Signal sessions
 *   - pre-key-{id}             → Signal pre-keys
 *   - sender-key-{id}          → Signal sender keys
 *
 * All values go through BufferJSON (de)serialization so that Node.js
 * Buffer objects survive the JSON → JSONB → JSON round-trip.
 */

import {
  initAuthCreds,
  BufferJSON,
  proto,
} from '@whiskeysockets/baileys'

// ─── helpers ────────────────────────────────────────────────────────────────

/**
 * Serialize a value so it can be stored in Supabase JSONB.
 * Converts Buffer instances to a JSON-safe representation.
 */
const serialize = (value) =>
  JSON.parse(JSON.stringify(value, BufferJSON.replacer))

/**
 * Deserialize a value coming out of Supabase JSONB.
 * Reconstructs Buffer instances from their JSON-safe representation.
 */
const deserialize = (value) =>
  JSON.parse(JSON.stringify(value), BufferJSON.reviver)

// ─── main export ────────────────────────────────────────────────────────────

/**
 * useSupabaseAuthState(supabase)
 * ─────────────────────────────
 * Returns a Baileys-compatible { state, saveCreds } pair backed by Supabase.
 *
 * @param {import('@supabase/supabase-js').SupabaseClient} supabase
 * @returns {Promise<{ state: import('@whiskeysockets/baileys').AuthenticationState, saveCreds: () => Promise<void> }>}
 */
export async function useSupabaseAuthState(supabase) {
  // ── 1. Bulk-load all existing auth rows from Supabase ────────────────────
  const { data: rows, error } = await supabase
    .from('whatsapp_auth')
    .select('key, value')

  if (error) {
    console.warn('[AUTH] Could not load auth state from Supabase:', error.message)
  }

  // In-memory cache keyed by auth key name
  const cache = {}
  for (const row of rows || []) {
    try {
      cache[row.key] = deserialize(row.value)
    } catch {
      // Skip malformed rows — Baileys will regenerate missing keys
    }
  }

  // ── 2. Build or restore credentials ──────────────────────────────────────
  const creds = cache['creds'] || initAuthCreds()

  // ── 3. Key persistence helpers ────────────────────────────────────────────

  const writeKey = async (key, value) => {
    const { error } = await supabase
      .from('whatsapp_auth')
      .upsert(
        { key, value: serialize(value), updated_at: new Date().toISOString() },
        { onConflict: 'key' },
      )
    if (error) {
      console.warn(`[AUTH] Failed to write key "${key}":`, error.message)
    }
  }

  const deleteKey = async (key) => {
    const { error } = await supabase
      .from('whatsapp_auth')
      .delete()
      .eq('key', key)
    if (error) {
      console.warn(`[AUTH] Failed to delete key "${key}":`, error.message)
    }
  }

  // ── 4. Build state object ─────────────────────────────────────────────────
  const state = {
    creds,

    keys: {
      /**
       * Retrieve Signal keys by type and IDs.
       * Called by Baileys before sending/receiving messages.
       */
      get: async (type, ids) => {
        const result = {}
        for (const id of ids) {
          const stored = cache[`${type}-${id}`]
          if (stored !== undefined) {
            // AppStateSyncKeyData must be reconstructed from proto definition
            if (type === 'app-state-sync-key') {
              result[id] = proto.Message.AppStateSyncKeyData.fromObject(stored)
            } else {
              result[id] = stored
            }
          }
        }
        return result
      },

      /**
       * Persist Signal keys to Supabase.
       * Called by Baileys after key rotation / new session creation.
       *
       * NOTE: lid-mapping keys are WhatsApp contact roster LIDs — they are
       * regenerated on every connection and do NOT need to be persisted.
       * Writing them floods Supabase with hundreds of upserts per connection.
       */
      set: async (data) => {
        const writes = []
        for (const type in data) {
          // Skip lid-mapping — contact roster data, not session keys
          if (type === 'lid-mapping') continue

          for (const id in data[type]) {
            const key = `${type}-${id}`
            // Also skip any key that starts with lid-mapping (full key form)
            if (key.startsWith('lid-mapping')) continue

            const value = data[type][id]
            if (value) {
              cache[key] = value
              writes.push(writeKey(key, value))
            } else {
              delete cache[key]
              writes.push(deleteKey(key))
            }
          }
        }
        await Promise.all(writes)
      },
    },
  }

  // ── 5. saveCreds — called by Baileys on 'creds.update' ────────────────────
  const saveCreds = async () => {
    await writeKey('creds', creds)
  }

  return { state, saveCreds }
}
