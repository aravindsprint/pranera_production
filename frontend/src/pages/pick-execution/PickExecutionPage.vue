<template>
  <div class="page">
    <AppHeader title="Pick Execution" :subtitle="order?.name" active="my-pick-orders" :show-back="true" />
    <div class="page-content">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="loadError" class="alert alert-error">{{ loadError }}</div>

      <template v-else-if="order">
        <div v-if="offlineAt || !isOnline" class="alert alert-warning"><div>
          Offline<span v-if="offlineAt"> — order as of {{ new Date(offlineAt).toLocaleString() }}</span>.
          <template v-if="candidates"> Scans are checked against {{ candidates.rolls.length }} rolls downloaded {{ new Date(candidatesAt).toLocaleString() }} and sent when the connection is back.</template>
          <template v-else> No roll list was downloaded for this order — open it once while online to scan offline.</template>
        </div></div>
        <div class="card">
          <div class="o-title">{{ order.work_order }} · {{ order.operation }}</div>
          <div class="o-sub">{{ order.production_item }}</div>
          <div class="o-sub">Job Card {{ order.job_card }}</div>
          <div v-if="order.batch_items.length" class="o-sub">
            Batches: {{ order.batch_items.map(b => `${b.batch} (${fmt(b.qty)})`).join(', ') }}
          </div>
          <div v-if="order.remarks" class="o-sub">💬 {{ order.remarks }}</div>
        </div>

        <div class="card" v-for="u in progress" :key="u.uom">
          <label class="form-label">Target — {{ u.uom }}</label>
          <div class="prog">
            <span class="prog__qty" :class="{ ok: u.within, over: u.over }">{{ fmt(u.total) }}</span>
            <span class="prog__target">/ {{ fmt(u.target) }} {{ u.uom }}</span>
          </div>
          <div class="bar"><div class="bar__fill" :class="{ ok: u.within, over: u.over }" :style="{ width: Math.min(100, u.total / (u.target || 1) * 100) + '%' }"></div></div>
          <div class="hint">Allowed {{ fmt(u.min) }} – {{ fmt(u.max) }} {{ u.uom }} (±{{ order.tolerance_pct }}%)</div>
          <div v-if="u.already" class="hint">{{ fmt(u.already) }} already picked earlier</div>
        </div>

        <div class="card">
          <div class="form-group">
            <label class="form-label">Source Warehouse *</label>
            <AsyncSelect v-model="source" :fetcher="warehouseFetcher" @select="o => saveWh(o?.value, null)" />
          </div>
          <div class="form-group">
            <label class="form-label">Target (WIP) Warehouse *</label>
            <AsyncSelect v-model="target" :fetcher="warehouseFetcher" @select="o => saveWh(null, o?.value)" />
          </div>
          <button class="btn btn-primary btn-full btn-lg" :disabled="!source || scanning" @click="scannerOpen = true">
            📷 {{ scanning ? 'Checking…' : 'Scan Roll' }}
          </button>
          <div v-if="scanError" class="alert alert-error" style="margin-top:10px">{{ scanError }}</div>
          <div v-if="lastScan" class="alert alert-success" style="margin-top:10px">Added {{ lastScan.roll_no }} · {{ fmt(lastScan.qty) }} {{ lastScan.uom }}</div>
        </div>

        <div class="card" v-if="scanned.length">
          <div class="section-title">Scanned ({{ scanned.length }})</div>
          <div class="roll" v-for="r in scanned" :key="r.roll_no" :class="{ 'roll--pending': pendingRolls.has(r.roll_no) }">
            <div class="roll__body">
              <div class="roll__no">{{ r.roll_no }} <span v-if="pendingRolls.has(r.roll_no)" class="badge badge-warning">on this device</span></div>
              <div class="roll__meta">{{ r.item_code }} · {{ r.batch_no }} · {{ fmt(r.qty) }} {{ r.uom }}</div>
            </div>
            <button class="roll__x" @click="remove(r.roll_no)">✕</button>
          </div>
        </div>

        <div class="card">
          <label class="form-label">Posting Date</label>
          <input v-model="postingDate" type="date" class="form-input" />
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="!canSubmit || submitting || !!pendingCountHere || !isOnline" @click="submit(false)">Save {{ seKind }} as Draft</button>
            <button class="btn btn-primary" :disabled="!canSubmit || submitting || !!pendingCountHere || !isOnline" @click="submit(true)">
              {{ submitting ? 'Submitting…' : 'Submit ' + seKind }}
            </button>
          </div>
          <div v-if="pendingCountHere" class="hint" style="margin-top:8px">
            {{ pendingCountHere }} scan change(s) still on this device — Submit unlocks once they reach ERPNext{{ isOnline ? ' (sending…)' : ' (needs the connection)' }}.
          </div>
          <div v-if="submitError" class="alert alert-error" style="margin-top:10px">{{ submitError }}</div>
        </div>
      </template>

      <ScannerModal v-model="scannerOpen" title="Scan roll sticker" @scanned="onScanned" />

      <div v-if="result" class="done-overlay">
        <div class="done-box">
          <div class="done-icon">✅</div>
          <div class="done-title">{{ result.stock_entry_submitted ? 'Material transferred' : seKind + ' saved as draft' }}</div>
          <div class="done-doc">{{ result.stock_entry }}</div>
          <div class="hint">{{ result.rolls }} rolls · {{ fmt(result.qty) }} · Pick list {{ result.pick_list }}</div>
          <button class="btn btn-primary btn-full" style="margin-top:14px" @click="router.push(BASE + '/my-pick-orders')">OK</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api, call } from '@/api/frappe'
import { db } from '@/db'
import { callOrQueue, isOnline } from '@/composables/useSync'
import { cached, cacheGet, cachePut } from '@/composables/useOffline'
import { BASE, fmt, today, warehouseFetcher } from '@/utils'

const route = useRoute()
const router = useRouter()
const order = ref(null)
const loading = ref(false)
const loadError = ref('')
const scanned = ref([])
const source = ref('')
const target = ref('')
const scannerOpen = ref(false)
const scanning = ref(false)
const scanError = ref('')
const lastScan = ref(null)
const postingDate = ref(today())
const submitting = ref(false)
const submitError = ref('')
const result = ref(null)
const offlineAt = ref(null)
const candidates = ref(null)      // { rolls, at } — for checking scans offline
const candidatesAt = ref(null)
const pendingItems = ref([])      // this order's queued scan / remove calls
const M = 'pranera_production.api.pick.'
const group = () => 'pick:' + route.query.order
const pendingCountHere = computed(() => pendingItems.value.length)
const pendingRolls = computed(() => new Set(pendingItems.value
  .filter(x => x.method.endsWith('scan_roll')).map(x => x.args.roll_no)))

async function refreshPending() {
  pendingItems.value = (await db.syncQueue.where('group').equals(group()).toArray()).filter(x => x._status !== 'synced')
}
// apply queued (not yet synced) scans / removals to the server's list
function overlay(list) {
  let out = [...list]
  for (const x of pendingItems.value) {
    if (x.method.endsWith('scan_roll') && x.args._row && !out.some(r => r.roll_no === x.args.roll_no)) out.push(x.args._row)
    if (x.method.endsWith('remove_scanned_roll')) out = out.filter(r => r.roll_no !== x.args.roll_no)
  }
  return out
}
async function loadCandidates() {
  const key = 'pickc:' + route.query.order
  if (isOnline.value) {
    try { cachePut(key, (await call(M + 'get_pick_candidates', { pick_order: route.query.order })).message) } catch { /* keep old */ }
  }
  const c = cacheGet(key)
  candidates.value = c?.data || null
  candidatesAt.value = c?.at || null
}
function parseRoll(text) {
  const parts = String(text || '').trim().split('#')
  return (parts.length >= 3 ? parts[parts.length - 1] : String(text || '')).trim()
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const r = await cached('pick:' + route.query.order, () => api.pickOrderDetail(route.query.order))
    order.value = r.data
    offlineAt.value = r.offline ? r.at : null
    await refreshPending()
    scanned.value = overlay(order.value.scanned_rolls || [])
    source.value = order.value.execution_source_warehouse || ''
    target.value = order.value.execution_target_warehouse || ''
  } catch (err) {
    loadError.value = err.message
  } finally {
    loading.value = false
  }
}

const progress = computed(() => {
  if (!order.value) return []
  const sess = {}
  for (const r of scanned.value) sess[r.uom || 'Kgs'] = (sess[r.uom || 'Kgs'] || 0) + (Number(r.qty) || 0)
  return (order.value.pick_qty_summary || []).map(t => {
    const total = (t.already_picked_qty || 0) + (sess[t.uom] || 0)
    return { uom: t.uom, target: t.total_qty, min: t.tolerance_min, max: t.tolerance_max, already: t.already_picked_qty,
             total, within: total >= t.tolerance_min && total <= t.tolerance_max, over: total > t.tolerance_max }
  })
})
// Same rule as the server (pick.py _mtm_naming_series): a pick to an
// "In Transit…" warehouse is an MT (MT/26/), anything else an MTM (MTM/26/).
const seKind = computed(() => (target.value || '').trim().toLowerCase().startsWith('in transit') ? 'MT' : 'MTM')
const canSubmit = computed(() => scanned.value.length && progress.value.length && progress.value.every(u => u.within))

async function saveWh(s, t) {
  try {
    await callOrQueue(M + 'update_execution_warehouse',
      { pick_order: order.value.name, source_warehouse: s || undefined, target_warehouse: t || undefined },
      `Warehouses · ${order.value.name}`, { group: group(), clientId: true })
    await refreshPending()
  } catch (err) { scanError.value = err.message }
}

async function onScanned(text) {
  scanError.value = ''
  lastScan.value = null
  scanning.value = true
  try {
    const rollNo = parseRoll(text)
    if (scanned.value.some(r => r.roll_no === rollNo)) throw new Error(`Roll ${rollNo} has already been scanned for this Order`)
    // offline (or queued behind other offline scans): check against the downloaded list
    const offlineMode = !isOnline.value || pendingCountHere.value > 0
    let localRow = null
    if (offlineMode) {
      const c = candidates.value?.rolls?.find(r => r.roll_no === rollNo)
      if (!c) throw new Error(candidates.value
        ? `Roll ${rollNo} is not one this order can take (as of ${new Date(candidatesAt.value).toLocaleString()}) — check it when online`
        : 'Offline — no roll list downloaded for this order yet')
      localRow = { ...c, warehouse: source.value }
    }
    const row = await callOrQueue(M + 'scan_roll',
      { pick_order: order.value.name, roll_no: rollNo, source_warehouse: source.value, ...(localRow ? { _row: localRow } : {}) },
      `Scan ${rollNo} · ${order.value.name}`, { group: group(), clientId: true })
    let added = row
    if (row?.queued) {
      added = localRow || (candidates.value?.rolls || []).find(r => r.roll_no === rollNo)
      if (!added) {  // went offline mid-scan and the roll isn't in the downloaded list
        throw new Error(`Saved offline, but roll ${rollNo} isn't in the downloaded list — it will be checked when sent`)
      }
      await refreshPending()
    }
    scanned.value = [...scanned.value, added]
    lastScan.value = added
  } catch (err) {
    scanError.value = err.message
  } finally {
    scanning.value = false
  }
}

async function remove(rollNo) {
  scanError.value = ''
  try {
    // a scan still on this device can just be dropped from the queue
    const q = pendingItems.value.find(x => x.method.endsWith('scan_roll') && x.args.roll_no === rollNo && x._status !== 'syncing')
    if (q) await db.syncQueue.delete(q.id)
    else await callOrQueue(M + 'remove_scanned_roll', { pick_order: order.value.name, roll_no: rollNo },
      `Remove ${rollNo} · ${order.value.name}`, { group: group(), clientId: true })
    await refreshPending()
    scanned.value = scanned.value.filter(r => r.roll_no !== rollNo)
  } catch (err) {
    scanError.value = err.message
  }
}

async function submit(final) {
  submitting.value = true
  submitError.value = ''
  try {
    result.value = await api.pickSubmit(order.value.name, postingDate.value, final ? 1 : 0)
  } catch (err) {
    submitError.value = err.message
  } finally {
    submitting.value = false
  }
}

const onSynced = async (e) => {
  if (e.detail?.group !== group()) return
  await refreshPending()
  if (!pendingItems.value.length) load()
}
onMounted(async () => {
  await load()
  loadCandidates()
  window.addEventListener('prod:queue-synced', onSynced)
})
onUnmounted(() => window.removeEventListener('prod:queue-synced', onSynced))
</script>

<style scoped>
.o-title { font-weight: 800; font-size: 15px; overflow-wrap: anywhere; }
.o-sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.prog { display: flex; align-items: baseline; gap: 6px; }
.prog__qty { font-size: 26px; font-weight: 800; }
.prog__qty.ok { color: #16a34a; }
.prog__qty.over { color: #dc2626; }
.prog__target { color: var(--slate-500); }
.bar { height: 8px; background: var(--slate-100); border-radius: 8px; overflow: hidden; margin: 8px 0; }
.bar__fill { height: 100%; background: var(--app-primary); }
.bar__fill.ok { background: #16a34a; }
.bar__fill.over { background: #dc2626; }
.hint { font-size: 12px; color: var(--slate-500); }
.roll { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--slate-100); }
.roll__body { flex: 1; min-width: 0; }
.roll__no { font-weight: 700; }
.roll__meta { font-size: 12px; color: var(--slate-500); overflow-wrap: anywhere; }
.roll--pending { background: #fffbeb; margin: 0 -8px; padding: 9px 8px; border-radius: 8px; }
.roll__x { border: none; background: none; color: var(--slate-400); font-size: 16px; padding: 6px; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
.done-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center; justify-content: center; z-index: 500; padding: 20px; }
.done-box { background: #fff; border-radius: 14px; padding: 24px; width: 100%; max-width: 360px; text-align: center; }
.done-icon { font-size: 40px; }
.done-title { font-size: 17px; font-weight: 800; margin: 6px 0; }
.done-doc { font-weight: 700; color: var(--app-primary); margin-bottom: 6px; }
</style>
