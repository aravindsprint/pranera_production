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

// Queue a whitelisted method call to replay when back online. Only used for
// idempotent calls (e.g. save_roll_inspection, which upserts by roll + job card).
export async function enqueueCall(method, args = {}, label = '') {
  await db.syncQueue.add({
    method,
    args: JSON.parse(JSON.stringify(args)),
    label,
    _status: 'pending',
    _retries: 0,
    _createdAt: new Date().toISOString(),
  })
  await refreshCounts()
  if (isOnline.value) flushQueue()
}

// Try online first; if the network is down, queue and resolve with { queued: true }.
export async function callOrQueue(method, args = {}, label = '') {
  if (isOnline.value) {
    try {
      const r = await call(method, args)
      return r?.message
    } catch (err) {
      // a real server-side validation error must surface, not be queued
      if (!/Failed to fetch|NetworkError|Load failed|network/i.test(err.message || '')) throw err
    }
  }
  await enqueueCall(method, args, label)
  return { queued: true }
}

export async function flushQueue() {
  if (isSyncing.value || !isOnline.value) return
  isSyncing.value = true
  try {
    const pending = await db.syncQueue.where('_status').equals('pending').sortBy('_createdAt')
    for (const item of pending) {
      await db.syncQueue.update(item.id, { _status: 'syncing' })
      try {
        await call(item.method, item.args)
        await db.syncQueue.update(item.id, { _status: 'synced', _syncedAt: new Date().toISOString() })
      } catch (err) {
        const retries = (item._retries || 0) + 1
        await db.syncQueue.update(item.id, {
          _status: retries >= 5 ? 'failed' : 'pending', _retries: retries, _error: err.message,
        })
      }
    }
    lastSyncAt.value = new Date().toISOString()
  } finally {
    isSyncing.value = false
    await refreshCounts()
  }
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
