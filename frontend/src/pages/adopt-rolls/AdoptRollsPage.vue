<template>
  <div class="page">
    <AppHeader title="Adopt Rolls" subtitle="Rolls moved before go-live" active="adopt-rolls" :show-back="true" />
    <div class="page-content">
      <div class="tabs">
        <button class="tab" :class="{ on: mode === 'wip' }" @click="mode = 'wip'">In WIP (Work Order)</button>
        <button class="tab" :class="{ on: mode === 'stock' }" @click="mode = 'stock'">In Stock (Batch)</button>
      </div>

      <!-- ── WIP ── -->
      <template v-if="mode === 'wip'">
        <div class="card">
          <div class="hint" style="margin-bottom:10px">For Work Orders whose MTM was made from the desk before go-live. Pick the transferred batch, then scan the rolls physically in the WIP. They are placed at the Work Order's current operation.</div>
          <label class="form-label">Work Order</label>
          <AsyncSelect v-model="wo" :fetcher="woFetcher" @select="o => o && loadWip(o.value)" />
        </div>
        <template v-if="wip">
          <div class="card">
            <div class="h">{{ wip.work_order.production_item }}</div>
            <div class="sub">Current operation <b>{{ wip.operation || '-' }}</b> · {{ wip.job_card || 'no job card' }} · WIP {{ wip.work_order.wip_warehouse }}</div>
            <div class="section-title" style="margin-top:12px">Transferred to this Work Order</div>
            <div v-if="!wip.rows.length" class="hint">No MTM found for this Work Order.</div>
            <label v-for="row in wip.rows" :key="row.item_code + row.batch_no" class="trow" :class="{ on: sel === row }">
              <input type="radio" name="trow" :checked="sel === row" @change="sel = row" />
              <div class="trow__b">
                <div class="trow__batch">{{ row.batch_no || '(no batch)' }}</div>
                <div class="sub">{{ row.item_code }}</div>
                <div class="sub">Transferred {{ fmt(row.transferred_qty, 3) }} {{ row.uom }} · adopted {{ row.adopted_rolls }} rolls / {{ fmt(row.adopted_qty, 3) }}<span v-if="row.batch_no"> · {{ row.rolls_in_batch }} rolls on this batch</span></div>
                <div class="bar"><div class="bar__f" :style="{ width: Math.min(100, row.adopted_qty / (row.transferred_qty || 1) * 100) + '%' }"></div></div>
              </div>
            </label>
          </div>
          <div class="card" v-if="sel">
            <label class="form-label">Weight (optional — defaults to the roll's current / greige weight)</label>
            <input v-model.number="weight" type="number" step="0.001" class="form-input" placeholder="kg" />
            <button class="btn btn-primary btn-full btn-lg" style="margin-top:10px" :disabled="busy" @click="scannerOpen = true">📷 Scan roll</button>
            <div v-if="msg" class="alert" :class="ok ? 'alert-success' : 'alert-error'" style="margin-top:10px">{{ msg }}</div>
          </div>
          <div class="card" v-if="wip.adopted_rolls.length">
            <div class="section-title">Adopted ({{ wip.adopted_rolls.length }})</div>
            <div class="roll" v-for="x in wip.adopted_rolls" :key="x.roll_no">
              <span class="roll__no">{{ x.roll_no }}</span><span class="sub roll__b">{{ x.batch_no }}</span><span>{{ fmt(x.weight, 3) }}</span>
              <button class="x" @click="undoWip(x.roll_no)">✕</button>
            </div>
          </div>
        </template>
      </template>

      <!-- ── Stock ── -->
      <template v-else>
        <div class="card">
          <div class="hint" style="margin-bottom:10px">For rolls dyed / finished before go-live that are now in stock (e.g. a …-D batch in the lot section). Scan each roll and enter its weight — it becomes that batch's item / batch / warehouse so it can be picked for the next process.</div>
          <label class="form-label">Batch</label>
          <AsyncSelect v-model="batch" :fetcher="batchFetcher" @select="o => o && loadStock(o.value)" />
        </div>
        <template v-if="stock">
          <div class="card">
            <div class="h">{{ stock.batch.item }}</div>
            <div class="sub">{{ stock.item_name }}</div>
            <div class="sub">Adopted {{ stock.adopted.length }} rolls / {{ fmt(stock.adopted_qty, 3) }} · {{ stock.rolls_with_batch }} rolls carry this as their original batch</div>
            <div class="section-title" style="margin-top:12px">Stock by warehouse</div>
            <div v-if="!stock.warehouses.length" class="hint">No stock for this batch.</div>
            <label v-for="w in stock.warehouses" :key="w.warehouse" class="trow" :class="{ on: wh === w.warehouse }">
              <input type="radio" name="wh" :checked="wh === w.warehouse" @change="wh = w.warehouse" />
              <div class="trow__b"><div class="trow__batch">{{ w.warehouse }}</div><div class="sub">{{ fmt(w.qty, 3) }} {{ stock.batch.stock_uom }}</div></div>
            </label>
          </div>
          <div class="card" v-if="wh">
            <label class="form-label">Roll weight now (kg)</label>
            <input v-model.number="weight" type="number" step="0.001" class="form-input" placeholder="leave empty to use greige weight" />
            <button class="btn btn-primary btn-full btn-lg" style="margin-top:10px" :disabled="busy" @click="scannerOpen = true">📷 Scan roll</button>
            <div v-if="msg" class="alert" :class="ok ? 'alert-success' : 'alert-error'" style="margin-top:10px">{{ msg }}</div>
          </div>
          <div class="card" v-if="stock.adopted.length">
            <div class="section-title">On this batch ({{ stock.adopted.length }})</div>
            <div class="roll" v-for="x in stock.adopted" :key="x.roll_no">
              <span class="roll__no">{{ x.roll_no }}</span><span class="sub roll__b">{{ x.warehouse }}</span><span>{{ fmt(x.weight, 3) }}</span>
              <button class="x" @click="undoStock(x.roll_no)">✕</button>
            </div>
          </div>
        </template>
      </template>

      <ScannerModal v-model="scannerOpen" title="Scan roll" :allow-manual="true" @scanned="onScanned" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
import { fmt } from '@/utils'

const mode = ref('wip')
const wo = ref('')
const wip = ref(null)
const sel = ref(null)
const batch = ref('')
const stock = ref(null)
const wh = ref('')
const weight = ref(null)
const scannerOpen = ref(false)
const busy = ref(false)
const msg = ref('')
const ok = ref(false)

watch(mode, () => { msg.value = ''; weight.value = null })

const woFetcher = async (txt) => (await api.searchWorkOrders(txt)).map(w => ({
  value: w.name, description: [w.production_item, w.color, w.status].filter(Boolean).join(' · '),
}))
const batchFetcher = async (txt) => (await api.adoptBatches(txt)).map(b => ({
  value: b.name, description: `${b.item} · ${fmt(b.batch_qty, 3)} ${b.stock_uom || ''}`,
}))

async function loadWip(name, keepSel = false) {
  const prev = sel.value
  wip.value = await api.adoptWipContext(name)
  sel.value = keepSel && prev ? wip.value.rows.find(r => r.item_code === prev.item_code && r.batch_no === prev.batch_no) || null
                              : (wip.value.rows.length === 1 ? wip.value.rows[0] : null)
}
async function loadStock(name) {
  stock.value = await api.adoptStockContext(name)
  if (!stock.value.warehouses.some(w => w.warehouse === wh.value)) {
    wh.value = stock.value.warehouses.length === 1 ? stock.value.warehouses[0].warehouse : ''
  }
}

async function onScanned(text) {
  busy.value = true
  msg.value = ''
  try {
    if (mode.value === 'wip') {
      const r = await api.adoptWipRoll(wip.value.work_order.name, sel.value.item_code, sel.value.batch_no, text, weight.value || undefined)
      ok.value = true
      msg.value = `${r.roll_no} adopted · ${fmt(r.weight, 3)} kg at ${r.operation || '-'}`
      await loadWip(wip.value.work_order.name, true)
    } else {
      const r = await api.adoptStockRoll(stock.value.batch.name, wh.value, text, weight.value || undefined)
      ok.value = true
      msg.value = `${r.roll_no} → ${stock.value.batch.name} · ${fmt(r.weight, 3)} kg`
      weight.value = null
      await loadStock(stock.value.batch.name)
    }
  } catch (err) {
    ok.value = false
    msg.value = err.message
  } finally {
    busy.value = false
  }
}

async function undoWip(rollNo) {
  try { await api.unadoptWipRoll(wip.value.work_order.name, rollNo); await loadWip(wip.value.work_order.name, true) }
  catch (err) { ok.value = false; msg.value = err.message }
}
async function undoStock(rollNo) {
  try { await api.unadoptStockRoll(stock.value.batch.name, rollNo); await loadStock(stock.value.batch.name) }
  catch (err) { ok.value = false; msg.value = err.message }
}
</script>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tab { flex: 1; padding: 10px; border-radius: 10px; border: 1.5px solid var(--slate-200); background: #fff; font-weight: 700; font-size: 13px; }
.tab.on { border-color: var(--app-primary); background: var(--app-primary); color: #fff; }
.hint { font-size: 12px; color: var(--slate-500); }
.h { font-weight: 800; overflow-wrap: anywhere; }
.sub { font-size: 12px; color: var(--slate-500); overflow-wrap: anywhere; }
.trow { display: flex; gap: 10px; padding: 10px; border: 1px solid var(--slate-200); border-radius: 10px; margin-bottom: 8px; align-items: flex-start; }
.trow.on { border-color: var(--app-primary); background: rgba(30,58,95,0.05); }
.trow input { margin-top: 3px; width: 18px; height: 18px; }
.trow__b { flex: 1; min-width: 0; }
.trow__batch { font-weight: 700; font-size: 13px; overflow-wrap: anywhere; }
.bar { height: 6px; background: var(--slate-100); border-radius: 6px; margin-top: 6px; overflow: hidden; }
.bar__f { height: 100%; background: var(--app-primary); }
.roll { display: flex; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--slate-100); font-size: 13px; }
.roll__no { font-weight: 700; min-width: 70px; }
.roll__b { flex: 1; }
.x { border: none; background: none; color: var(--slate-400); font-size: 15px; padding: 4px 6px; }
</style>
