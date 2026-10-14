<template>
  <div class="page">
    <AppHeader title="Pick Execution" :subtitle="order?.name" active="my-pick-orders" :show-back="true" />
    <div class="page-content">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="loadError" class="alert alert-error">{{ loadError }}</div>

      <template v-else-if="order">
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
          <div class="roll" v-for="r in scanned" :key="r.roll_no">
            <div class="roll__body">
              <div class="roll__no">{{ r.roll_no }}</div>
              <div class="roll__meta">{{ r.item_code }} · {{ r.batch_no }} · {{ fmt(r.qty) }} {{ r.uom }}</div>
            </div>
            <button class="roll__x" @click="remove(r.roll_no)">✕</button>
          </div>
        </div>

        <div class="card">
          <label class="form-label">Posting Date</label>
          <input v-model="postingDate" type="date" class="form-input" />
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="!canSubmit || submitting" @click="submit(false)">Save MTM as Draft</button>
            <button class="btn btn-primary" :disabled="!canSubmit || submitting" @click="submit(true)">
              {{ submitting ? 'Submitting…' : 'Submit MTM' }}
            </button>
          </div>
          <div v-if="submitError" class="alert alert-error" style="margin-top:10px">{{ submitError }}</div>
        </div>
      </template>

      <ScannerModal v-model="scannerOpen" title="Scan roll sticker" @scanned="onScanned" />

      <div v-if="result" class="done-overlay">
        <div class="done-box">
          <div class="done-icon">✅</div>
          <div class="done-title">{{ result.stock_entry_submitted ? 'Material transferred' : 'MTM saved as draft' }}</div>
          <div class="done-doc">{{ result.stock_entry }}</div>
          <div class="hint">{{ result.rolls }} rolls · {{ fmt(result.qty) }} · Pick list {{ result.pick_list }}</div>
          <button class="btn btn-primary btn-full" style="margin-top:14px" @click="router.push(BASE + '/my-pick-orders')">OK</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
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

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    order.value = await api.pickOrderDetail(route.query.order)
    scanned.value = order.value.scanned_rolls || []
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
const canSubmit = computed(() => scanned.value.length && progress.value.length && progress.value.every(u => u.within))

async function saveWh(s, t) {
  try { await api.pickWarehouses(order.value.name, s || undefined, t || undefined) } catch (err) { scanError.value = err.message }
}

async function onScanned(text) {
  scanError.value = ''
  lastScan.value = null
  scanning.value = true
  try {
    const row = await api.pickScan(order.value.name, text, source.value)
    scanned.value = [...scanned.value, row]
    lastScan.value = row
  } catch (err) {
    scanError.value = err.message
  } finally {
    scanning.value = false
  }
}

async function remove(rollNo) {
  scanError.value = ''
  try {
    await api.pickRemove(order.value.name, rollNo)
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

onMounted(load)
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
.roll__x { border: none; background: none; color: var(--slate-400); font-size: 16px; padding: 6px; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
.done-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center; justify-content: center; z-index: 500; padding: 20px; }
.done-box { background: #fff; border-radius: 14px; padding: 24px; width: 100%; max-width: 360px; text-align: center; }
.done-icon { font-size: 40px; }
.done-title { font-size: 17px; font-weight: 800; margin: 6px 0; }
.done-doc { font-weight: 700; color: var(--app-primary); margin-bottom: 6px; }
</style>
