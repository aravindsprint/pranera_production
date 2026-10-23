// src/composables/useSync.js
// Connectivity probe + offline queue + lookup-table cache.
// Same connectivity rules as the Knit App (see pranera_knit useSync.js):
// never trust navigator.onLine, ask the server; any HTTP answer = online.
import { ref, onMounted, onUnmounted } from 'vue'
import { db } from '@/db'
import { call } from '@/api/frappe'

export const isOnline = ref(navigator.onLine)
export const isSyncing = ref(false)
export const pendingCount = ref(0)
export const failedCount = ref(0)
export const lastSyncAt = ref(null)

const PROBE_URL = '/api/method/ping'
const PROBE_TIMEOUT_MS = 8000
const PROBE_EVERY_ONLINE_MS = 15_000
const PROBE_EVERY_OFFLINE_MS = 4_000

let syncTimer = null
let reachTimer = null
let probeInFlight = null

function normalizeRows(res) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.message)) return res.message
  return []
}

function setOnline(next) {
  if (isOnline.value === next) return
  isOnline.value = next
  if (next) { flushQueue(); syncLookupTables() }
}

async function probeOnce() {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
  try {
    const r = await fetch(`${PROBE_URL}?_=${Date.now()}`, { credentials: 'include', cache: 'no-store', signal: ctrl.signal })
    return !(r.status === 502 || r.status === 503 || r.status === 504)
  } catch {
    return false
  } finally {
    clearTimeout(t)
  }
}

export function checkReachable() {
  if (probeInFlight) return probeInFlight
  probeInFlight = probeOnce()
    .then(ok => { setOnline(ok); return ok })
    .finally(() => { probeInFlight = null })
  return probeInFlight
}

function onApiOk() { if (!isOnline.value) setOnline(true) }

function scheduleProbe() {
  clearTimeout(reachTimer)
  reachTimer = setTimeout(async () => { await checkReachable(); scheduleProbe() },
    isOnline.value ? PROBE_EVERY_ONLINE_MS : PROBE_EVERY_OFFLINE_MS)
}

async function refreshCounts() {
  pendingCount.value = await db.syncQueue.where('_status').equals('pending').count()
  failedCount.value = await db.syncQueue.where('_status').equals('failed').count()
}

const NETWORK_ERR = /Failed to fetch|NetworkError|Load failed|network|BackendUnreachable|timed? ?out|502|503|504/i
const MAX_RETRIES = 3

// args starting with "_" are for the device only (e.g. a row to show while
// the call waits in the queue) and are never sent to the server
const wire = (a) => Object.fromEntries(Object.entries(a || {}).filter(([k]) => !k.startsWith('_')))

export function newClientId() {
  return (crypto.randomUUID && crypto.randomUUID()) ||
    Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
}

// 'YYYY-MM-DD HH:mm:ss' in device local time — what Frappe expects for a Datetime
export function localNow() {
  const d = new Date(), p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// Queue a whitelisted method call to replay when back online. Only for calls
// the server treats idempotently (upsert, or a client_id it recognises).
export async function enqueueCall(method, args = {}, label = '', group = null) {
  await db.syncQueue.add({
    method,
    args: JSON.parse(JSON.stringify(args)),
    label,
    group,
    _status: 'pending',
    _retries: 0,
    _createdAt: new Date().toISOString(),
  })
  await refreshCounts()
  if (isOnline.value) flushQueue()
}

export async function groupHasPending(group) {
  if (!group) return false
  return (await db.syncQueue.where('group').equals(group).filter(x => x._status !== 'synced').count()) > 0
}

// Try online first; if the network is down, queue and resolve with
// { queued: true, client_id }. opts.group keeps calls on one document in
// order: while earlier calls of the group are still queued, this one queues
// too. opts.clientId adds a client_id the server uses to spot a re-send.
export async function callOrQueue(method, args = {}, label = '', opts = {}) {
  const a = { ...args }
  if (opts.clientId) a.client_id = a.client_id || newClientId()
  const mustQueue = await groupHasPending(opts.group)
  if (isOnline.value && !mustQueue) {
    try {
      const r = await call(method, wire(a))
      return r?.message
    } catch (err) {
      // a real server-side validation error must surface, not be queued
      if (!NETWORK_ERR.test(err.message || '')) throw err
    }
  }
  await enqueueCall(method, a, label, opts.group || null)
  return { queued: true, client_id: a.client_id }
}

export async function flushQueue() {
  if (isSyncing.value || !isOnline.value) return
  isSyncing.value = true
  try {
    const pending = await db.syncQueue.where('_status').anyOf('pending', 'syncing').sortBy('_createdAt')
    const blocked = new Set()
    // groups with a failed item stay blocked until it's retried or discarded
    for (const f of await db.syncQueue.where('_status').equals('failed').toArray()) if (f.group) blocked.add(f.group)
    for (const item of pending) {
      if (item.group && blocked.has(item.group)) continue
      await db.syncQueue.update(item.id, { _status: 'syncing' })
      try {
        const r = await call(item.method, wire(item.args))
        await db.syncQueue.update(item.id, { _status: 'synced', _syncedAt: new Date().toISOString(), _result: r?.message ?? null })
        window.dispatchEvent(new CustomEvent('prod:queue-synced', { detail: { group: item.group, method: item.method } }))
      } catch (err) {
        if (NETWORK_ERR.test(err.message || '')) {
          // still offline — try again later, no retry counted
          await db.syncQueue.update(item.id, { _status: 'pending' })
          break
        }
        const retries = (item._retries || 0) + 1
        await db.syncQueue.update(item.id, {
          _status: retries >= MAX_RETRIES ? 'failed' : 'pending', _retries: retries, _error: err.message,
        })
        if (item.group) blocked.add(item.group)
      }
    }
    lastSyncAt.value = new Date().toISOString()
    // keep the last 100 synced items for the queue page
    const synced = await db.syncQueue.where('_status').equals('synced').sortBy('_createdAt')
    if (synced.length > 100) await db.syncQueue.bulkDelete(synced.slice(0, synced.length - 100).map(x => x.id))
  } finally {
    isSyncing.value = false
    await refreshCounts()
  }
}

export async function retryItem(id) {
  await db.syncQueue.update(id, { _status: 'pending', _retries: 0, _error: null })
  await refreshCounts()
  flushQueue()
}

export async function discardItem(id) {
  await db.syncQueue.delete(id)
  await refreshCounts()
  flushQueue()
}

export async function syncLookupTables() {
  if (!isOnline.value) return
  const { syncWarehouses, syncPurchaseOrders, syncSubcontractingOrders } = await import('@/api/frappe')
  const tasks = [
    { fn: syncWarehouses, table: 'warehouses' },
    { fn: syncPurchaseOrders, table: 'purchase_orders' },
    { fn: syncSubcontractingOrders, table: 'subcontracting_orders' },
  ]
  for (const t of tasks) {
    try {
      const rows = normalizeRows(await t.fn())
      await db[t.table].bulkPut(rows.map(r => ({ ...r, id: r.name })))
    } catch (err) {
      console.warn(`Sync failed for ${t.table}:`, err.message)
    }
  }
}

export function useSync() {
  const onHint = () => checkReachable()
  const onWake = () => { if (document.visibilityState === 'visible') checkReachable() }
  onMounted(async () => {
    window.addEventListener('online', onHint)
    window.addEventListener('offline', onHint)
    window.addEventListener('focus', onWake)
    document.addEventListener('visibilitychange', onWake)
    window.addEventListener('prod:api-ok', onApiOk)
    await refreshCounts()
    syncTimer = setInterval(flushQueue, 10_000)
    checkReachable()
    scheduleProbe()
    if (isOnline.value) { flushQueue(); syncLookupTables() }
  })
  onUnmounted(() => {
    window.removeEventListener('online', onHint)
    window.removeEventListener('offline', onHint)
    window.removeEventListener('focus', onWake)
    document.removeEventListener('visibilitychange', onWake)
    window.removeEventListener('prod:api-ok', onApiOk)
    clearInterval(syncTimer)
    clearTimeout(reachTimer)
  })
  return { isOnline, isSyncing, pendingCount, failedCount, lastSyncAt, flushQueue, syncLookupTables }
}
