<template>
  <div class="page">
    <AppHeader title="Manufacture (MF)" :subtitle="ctx?.work_order.name" active="manufacture" :show-back="!!ctx" />
    <div class="page-content no-print">

      <!-- Work orders with rolls in process -->
      <template v-if="!ctx">
        <input v-model="txt" class="form-input" placeholder="Search work order / item" @input="debounced" style="margin-bottom:12px" />
        <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
        <div v-else-if="!wos.length" class="empty-state"><div class="empty-state__icon">🏭</div><div class="empty-state__title">No rolls in process</div></div>
        <button v-for="w in wos" :key="w.work_order" class="card wo" @click="open(w.work_order)">
          <div class="wo__top"><b>{{ w.work_order }}</b><span class="badge badge-info">{{ w.rolls }} rolls</span></div>
          <div class="wo__meta">{{ w.production_item }}<span v-if="w.color"> · {{ w.color }}</span></div>
          <div class="wo__meta">{{ fmt(w.weight) }} kg in process · {{ w.processes }}</div>
          <div class="wo__meta">Produced {{ fmt(w.produced_qty) }} / {{ fmt(w.qty) }}</div>
        </button>
      </template>

      <template v-else>
        <div class="card">
          <div class="h">{{ ctx.fg_item }}</div>
          <div class="sub">{{ ctx.work_order.item_name }}</div>
          <div class="sub">Last operation <b>{{ ctx.last_operation }}</b> · {{ ctx.last_job_card }} <span class="badge" :class="statusClass(ctx.last_job_card_status)">{{ ctx.last_job_card_status }}</span></div>
          <div class="mode" :class="'mode--' + ctx.weight_mode">
            <template v-if="ctx.weight_mode === 'keep'">Wet process — rolls keep their previous weight.</template>
            <template v-else-if="ctx.weight_mode === 'inspection'">Weight comes from each roll's inspection{{ ctx.require_inspection ? ' (inspection required)' : '' }}.</template>
            <template v-else>Weigh every roll.</template>
          </div>
          <div v-if="ctx.last_job_card_status && ctx.last_job_card_status !== 'Completed'" class="alert alert-warning" style="margin-top:10px">
            Complete Job Card {{ ctx.last_job_card }} before the MF (ERPNext needs the operation completed).
            <button class="btn btn-ghost" style="margin-top:6px" @click="router.push(BASE + '/job-cards/' + encodeURIComponent(ctx.last_job_card))">Open Job Card</button>
          </div>
        </div>

        <div class="card">
          <div class="sel-bar">
            <button class="btn btn-ghost" @click="selectAll(true)">Select all</button>
            <button class="btn btn-ghost" @click="selectAll(false)">Clear</button>
            <button class="btn btn-primary" @click="scannerOpen = true">📷 Scan</button>
          </div>
          <div v-if="scanMsg" class="alert" :class="scanOk ? 'alert-success' : 'alert-error'">{{ scanMsg }}</div>
          <div class="roll" v-for="r in ctx.rolls" :key="r.roll_no" :class="{ 'roll--off': !r.eligible }">
            <input type="checkbox" v-model="sel[r.roll_no]" :disabled="!r.eligible" />
            <div class="roll__body">
              <div class="roll__no">{{ r.roll_no }}
                <span v-if="r.inspection" class="badge" :class="gradeClass(r.inspection.grade)">G{{ r.inspection.grade }}</span>
                <span v-else-if="ctx.weight_mode === 'inspection'" class="badge badge-warning">not inspected</span>
              </div>
              <div class="roll__meta">{{ r.batch_no }} · before {{ fmt(r.weight_before, 3) }}<span v-if="r.total_qty"> · {{ r.total_qty }} pcs</span></div>
              <div v-if="!r.eligible" class="roll__meta">{{ r.not_eligible_reason }}</div>
            </div>
            <input v-if="ctx.weight_mode !== 'keep'" v-model.number="w[r.roll_no]" type="number" step="0.001" class="form-input roll__w"
                   :disabled="!r.eligible" placeholder="kg" />
            <span v-else class="roll__keep">{{ fmt(r.weight_before, 3) }}</span>
          </div>
        </div>

        <div class="card">
          <div class="totals">
            <div><span>Rolls</span><b>{{ selected.length }}</b></div>
            <div><span>Before</span><b>{{ fmt(sumBefore, 3) }}</b></div>
            <div><span>After</span><b>{{ fmt(sumAfter, 3) }}</b></div>
            <div><span>Loss</span><b :class="{ neg: sumBefore - sumAfter < 0 }">{{ fmt(sumBefore - sumAfter, 3) }} ({{ fmt(lossPct) }}%)</b></div>
          </div>
          <div v-if="ctx.chemicals_in_wip.length" class="hint">Chemicals in WIP ({{ ctx.chemicals_in_wip.length }} lines) are consumed in proportion — {{ isFinal ? 'this is the last MF, all of it' : fmt(share * 100) + '% of it' }}.</div>
          <label class="form-label" style="margin-top:12px">Finished Batch</label>
          <input v-model="fgBatch" class="form-input" placeholder="Leave empty to auto-create" />
          <div class="hint" v-if="ctx.default_fg_batch">Defaults to the batch of the first MF so the lot stays one batch.</div>
          <label class="form-label" style="margin-top:12px">Posting Date</label>
          <input v-model="postingDate" type="date" class="form-input" />
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="!canSubmit || saving" @click="submit(false)">Save Draft</button>
            <button class="btn btn-primary" :disabled="!canSubmit || saving" @click="submit(true)">{{ saving ? 'Submitting…' : 'Submit MF' }}</button>
          </div>
          <div v-if="error" class="alert alert-error" style="margin-top:10px">{{ error }}</div>
        </div>
      </template>

      <ScannerModal v-model="scannerOpen" title="Scan roll to select" :allow-manual="true" @scanned="onScanned" />

      <div v-if="result" class="ov">
        <div class="ov__box">
          <div class="done-icon">✅</div>
          <div class="h" style="text-align:center">{{ result.stock_entry }} {{ result.submitted ? 'submitted' : 'saved as draft' }}</div>
          <div class="sub" style="text-align:center">{{ result.fg_item }} · {{ result.fg_batch || 'batch on submit' }} · {{ fmt(result.fg_qty, 3) }}</div>
          <div class="sub" style="text-align:center" v-if="result.packing_list">Roll Packing List {{ result.packing_list }}</div>
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="!result.fg_batch" @click="printStickers">🖨 Stickers</button>
            <button class="btn btn-primary" @click="finish">Done</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Print area: one sticker per roll -->
    <div class="print-only">
      <div v-for="s in stickers" :key="s.roll_no" class="sticker">
        <img :src="s.qr" class="sticker__qr" />
        <div class="sticker__txt">
          <div class="sticker__roll">{{ s.roll_no }}</div>
          <div>{{ s.item }}</div>
          <div>{{ s.batch }}</div>
          <div><b>{{ fmt(s.weight, 2) }} kg</b><span v-if="s.grade"> · G{{ s.grade }}</span></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import QRCode from 'qrcode'
import AppHeader from '@/components/AppHeader.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
import { BASE, fmt, today, statusClass, gradeClass, isPcs } from '@/utils'

const route = useRoute()
const router = useRouter()
const txt = ref('')
const wos = ref([])
const loading = ref(false)
const ctx = ref(null)
const sel = reactive({})
const w = reactive({})
const fgBatch = ref('')
const postingDate = ref(today())
const saving = ref(false)
const error = ref('')
const result = ref(null)
const scannerOpen = ref(false)
const scanMsg = ref('')
const scanOk = ref(false)
const stickers = ref([])
let t = null

async function list() {
  loading.value = true
  try { wos.value = await api.mfWorkOrders(txt.value) } catch (err) { error.value = err.message }
  loading.value = false
}
function debounced() { clearTimeout(t); t = setTimeout(list, 300) }

async function open(wo) {
  error.value = ''
  result.value = null
  Object.keys(sel).forEach(k => delete sel[k])
  Object.keys(w).forEach(k => delete w[k])
  ctx.value = await api.mfContext(wo)
  fgBatch.value = ctx.value.default_fg_batch || ''
  for (const r of ctx.value.rolls) {
    if (r.weight_after) w[r.roll_no] = r.weight_after
  }
}

const selected = computed(() => (ctx.value?.rolls || []).filter(r => sel[r.roll_no]))
const weightAfter = (r) => ctx.value.weight_mode === 'keep' ? r.weight_before : (Number(w[r.roll_no]) || 0)
const sumBefore = computed(() => selected.value.filter(r => !isPcs(r.uom)).reduce((s, r) => s + (Number(r.weight_before) || 0), 0))
const sumAfter = computed(() => selected.value.filter(r => !isPcs(r.uom)).reduce((s, r) => s + weightAfter(r), 0))
const lossPct = computed(() => sumBefore.value ? (sumBefore.value - sumAfter.value) / sumBefore.value * 100 : 0)
const isFinal = computed(() => ctx.value && selected.value.length === ctx.value.rolls.length)
const share = computed(() => {
  const all = (ctx.value?.rolls || []).filter(r => !isPcs(r.uom)).reduce((s, r) => s + (Number(r.weight_before) || 0), 0)
  return all ? Math.min(1, sumBefore.value / all) : 1
})
const canSubmit = computed(() => selected.value.length && selected.value.every(r => weightAfter(r) > 0) &&
  !(ctx.value.weight_mode === 'inspection' && ctx.value.require_inspection && selected.value.some(r => !r.inspection)))

function selectAll(on) {
  for (const r of ctx.value.rolls) if (r.eligible) sel[r.roll_no] = on
}

function onScanned(text) {
  const parts = String(text).split('#')
  const rn = parts.length >= 3 ? parts[parts.length - 1] : String(text).trim()
  const r = ctx.value.rolls.find(x => x.roll_no === rn)
  if (!r) { scanOk.value = false; scanMsg.value = `Roll ${rn} is not in process for this Work Order`; return }
  if (!r.eligible) { scanOk.value = false; scanMsg.value = `Roll ${rn}: ${r.not_eligible_reason}`; return }
  sel[rn] = true
  scanOk.value = true
  scanMsg.value = `Selected ${rn}`
}

async function submit(final) {
  saving.value = true
  error.value = ''
  try {
    result.value = await api.createMf({
      work_order: ctx.value.work_order.name,
      rolls: selected.value.map(r => ({ roll_no: r.roll_no, weight_after: weightAfter(r) })),
      fg_batch: fgBatch.value || undefined,
      posting_date: postingDate.value,
      submit_stock_entry: final ? 1 : 0,
    })
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function printStickers() {
  const byRoll = Object.fromEntries(ctx.value.rolls.map(r => [r.roll_no, r]))
  stickers.value = await Promise.all(result.value.rolls.map(async (r) => ({
    roll_no: r.roll_no,
    item: result.value.fg_item,
    batch: result.value.fg_batch,
    weight: r.weight,
    grade: byRoll[r.roll_no]?.inspection?.grade,
    // same sticker format the knit app scans: item_code#batch#roll_no
    qr: await QRCode.toDataURL(`${result.value.fg_item}#${result.value.fg_batch}#${r.roll_no}`, { margin: 1, width: 180 }),
  })))
  await nextTick()
  window.print()
}

async function finish() {
  const wo = ctx.value.work_order.name
  result.value = null
  await open(wo)
  if (!ctx.value.rolls.length) { ctx.value = null; list() }
}

onMounted(async () => {
  if (route.query.wo) await open(String(route.query.wo))
  else list()
})
</script>

<style scoped>
.wo { display: block; width: 100%; text-align: left; }
.wo__top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.wo__meta { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.h { font-weight: 800; overflow-wrap: anywhere; }
.sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.mode { margin-top: 10px; font-size: 13px; padding: 8px 10px; border-radius: 8px; background: var(--blue-100); color: var(--blue-600); }
.mode--keep { background: var(--amber-100); color: var(--amber-600); }
.sel-bar { display: flex; gap: 8px; margin-bottom: 10px; }
.sel-bar .btn { flex: 1; padding: 9px 10px; }
.roll { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--slate-100); }
.roll input[type=checkbox] { width: 20px; height: 20px; flex-shrink: 0; }
.roll--off { opacity: 0.5; }
.roll__body { flex: 1; min-width: 0; }
.roll__no { font-weight: 700; display: flex; gap: 6px; align-items: center; }
.roll__meta { font-size: 11px; color: var(--slate-500); overflow-wrap: anywhere; }
.roll__w { width: 96px; flex-shrink: 0; padding: 8px; }
.roll__keep { font-weight: 700; }
.totals { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.totals div { display: flex; flex-direction: column; font-size: 12px; color: var(--slate-500); }
.totals b { font-size: 15px; color: var(--slate-900); }
.totals .neg { color: var(--red-600); }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
.ov { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center; justify-content: center; z-index: 500; padding: 20px; }
.ov__box { background: #fff; border-radius: 14px; padding: 22px; width: 100%; max-width: 380px; }
.done-icon { font-size: 40px; text-align: center; }
.print-only { display: none; }
@media print {
  .no-print, :deep(.ah-header) { display: none !important; }
  .print-only { display: block; }
  .sticker { display: flex; gap: 8px; align-items: center; width: 100mm; height: 50mm; padding: 3mm; page-break-after: always; font-size: 11pt; }
  .sticker__qr { width: 40mm; height: 40mm; }
  .sticker__roll { font-size: 20pt; font-weight: 800; }
}
</style>
