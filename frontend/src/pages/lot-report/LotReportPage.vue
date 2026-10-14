<template>
  <div class="page">
    <AppHeader title="Lot Inspection Report" :subtitle="r?.header.report_no" active="lot-report" class="no-print" />
    <div class="page-content wide">
      <div class="card no-print">
        <label class="form-label">Inspection Job Card</label>
        <AsyncSelect v-model="jobCard" :fetcher="jcFetcher" placeholder="Search job card / work order / item" @select="o => o && load(o.value)" />
        <div class="btn-row" v-if="r">
          <button class="btn btn-outline" @click="print('external')">🖨 External PDF</button>
          <button class="btn btn-primary" @click="print('internal')">🖨 Internal PDF</button>
        </div>
        <div class="hint" v-if="r">External hides the knitting / dyeing / stentering units and summary defect counts. Choose "Save as PDF" in the print dialog.</div>
      </div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="error" class="alert alert-error no-print">{{ error }}</div>

      <div v-if="r" class="report" :class="'fmt-' + format">
        <div class="rep-title">{{ r.type === 'Collar Cuff' ? 'Collar / Cuff' : 'Fabric' }} Inspection Report</div>

        <!-- Header -->
        <table class="hdr">
          <tbody>
            <tr><th>Commercial Name</th><td>{{ h.commercial_name }}</td><th>Report No</th><td>{{ h.report_no }}</td></tr>
            <tr><th>Item Code</th><td>{{ h.item_code }}</td><th>No of Rolls</th><td>{{ h.no_of_rolls }}</td></tr>
            <tr><th>Batch No</th><td>{{ h.batch_no }}</td><th>Date</th><td>{{ h.date }}</td></tr>
            <tr><th>Fb Width &amp; GSM</th><td>{{ h.fabric_required_width || '-' }} / {{ h.fabric_required_gsm || '-' }}</td>
                <template v-if="format === 'internal'"><th>Knitting</th><td>{{ h.knitting }}</td></template><template v-else><th></th><td></td></template></tr>
            <tr><th>Description</th><td>{{ h.description }}</td>
                <template v-if="format === 'internal'"><th>Dyeing</th><td>{{ h.dyeing }}</td></template><template v-else><th></th><td></td></template></tr>
            <tr><th>Total Rolls Weight</th><td>{{ fmt(h.total_rolls_weight, 3) }}</td>
                <template v-if="format === 'internal'"><th>Stentering</th><td>{{ h.stentering }}</td></template><template v-else><th></th><td></td></template></tr>
            <tr><th>DC Weight</th><td>{{ fmt(h.dc_weight, 3) }}</td><th>Diff Weight</th><td>{{ fmt(h.diff_weight, 3) }}</td></tr>
            <tr><th>Avg Point In Lot</th><td>{{ fmt(h.avg_point_in_lot, 3) }}</td><th>Work Order</th><td>{{ h.work_order }}</td></tr>
            <tr v-if="format === 'internal'"><th>WPI / CPI (actual)</th><td>{{ h.wpi || '-' }} ({{ h.wpi_actual || '-' }}) / {{ h.cpi || '-' }} ({{ h.cpi_actual || '-' }})</td><th>Checker</th><td>{{ h.checker }}</td></tr>
          </tbody>
        </table>

        <div class="sec-title">Defect Details</div>
        <div v-for="(chunk, ci) in chunks" :key="ci" class="chunk">
          <div class="chunk-head" v-if="ci > 0">Report No : <b>{{ h.report_no }}</b></div>
          <table class="grid">
            <thead>
              <tr><th class="lbl">Mistake Name</th><th>Total</th><th v-for="x in chunk" :key="x.roll_no">{{ x.roll_no }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in chunkMistakes(chunk)" :key="m">
                <td class="lbl">{{ m }}</td>
                <td class="num b">{{ chunk.reduce((s, x) => s + (x.mistakes[m] || 0), 0) || '' }}</td>
                <td v-for="x in chunk" :key="x.roll_no" class="num">{{ x.mistakes[m] || '' }}</td>
              </tr>
              <tr class="tot">
                <td class="lbl">Total</td>
                <td class="num">{{ chunk.reduce((s, x) => s + x.total_points, 0) }}</td>
                <td v-for="x in chunk" :key="x.roll_no" class="num">{{ x.total_points }}</td>
              </tr>
              <tr v-for="row in metricRows" :key="row.label" :class="{ grade: row.key === 'grade' }">
                <td class="lbl">{{ row.label }}</td>
                <td></td>
                <td v-for="x in chunk" :key="x.roll_no" class="num" :class="row.key === 'grade' && String(x.grade) === '3' ? 'g3' : ''">{{ row.fmt ? row.fmt(x[row.key]) : x[row.key] }}</td>
              </tr>
              <tr v-for="f in r.flags" :key="f.key">
                <td class="lbl">{{ f.label }}</td>
                <td></td>
                <td v-for="x in chunk" :key="x.roll_no" class="num">{{ x[f.key] }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="sec-title">Summary Details</div>
        <table class="grid summary">
          <thead>
            <tr>
              <th>S.No</th><th>Grade</th><th>No of Rolls</th><th>Roll Weight</th>
              <th v-if="r.type === 'Collar Cuff'">Pcs</th><th>Percentage</th>
              <template v-if="format === 'internal'"><th v-for="f in r.flags" :key="f.key">{{ f.label }}</th></template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in r.summary" :key="s.grade">
              <td>{{ i + 1 }}</td><td :class="s.grade === '3' ? 'g3' : ''">{{ s.grade }}</td><td class="num">{{ s.no_of_rolls }}</td>
              <td class="num">{{ format === 'internal' ? fmt(s.weight, 3) : Math.round(s.weight) }}</td>
              <td v-if="r.type === 'Collar Cuff'" class="num">{{ s.qty_pcs }}</td>
              <td class="num">{{ Math.round(s.percentage) }}%</td>
              <template v-if="format === 'internal'"><td v-for="f in r.flags" :key="f.key" class="num">{{ s[f.key] }}</td></template>
            </tr>
            <tr class="tot">
              <td></td><td>Total</td><td class="num">{{ r.summary.reduce((a, s) => a + s.no_of_rolls, 0) }}</td>
              <td class="num">{{ fmt(h.total_rolls_weight, 3) }}</td>
              <td v-if="r.type === 'Collar Cuff'" class="num">{{ r.summary.reduce((a, s) => a + s.qty_pcs, 0) }}</td>
              <td class="num">100%</td>
              <template v-if="format === 'internal'"><td v-for="f in r.flags" :key="f.key"></td></template>
            </tr>
          </tbody>
        </table>
        <div class="sign">
          <div>Checked by</div><div>Approved by</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import { api } from '@/api/frappe'
import { fmt } from '@/utils'

const ROLLS_PER_TABLE = 8 // same as the Ionic pivot

const route = useRoute()
const jobCard = ref('')
const r = ref(null)
const loading = ref(false)
const error = ref('')
const format = ref('internal')

const h = computed(() => r.value?.header || {})
const chunks = computed(() => {
  const rolls = r.value?.rolls || []
  const out = []
  for (let i = 0; i < rolls.length; i += ROLLS_PER_TABLE) out.push(rolls.slice(i, i + ROLLS_PER_TABLE))
  return out
})
// mistake rows: only those that occur in the chunk, in lot order (highest total first)
function chunkMistakes(chunk) {
  return (r.value?.mistakes || []).map(m => m.mistake).filter(m => chunk.some(x => x.mistakes[m]))
}
const metricRows = computed(() => {
  const f2 = (v) => (v === null || v === undefined || v === '') ? '' : Number(v).toFixed(2)
  const f3 = (v) => (v === null || v === undefined || v === '') ? '' : Number(v).toFixed(3)
  if (r.value?.type === 'Collar Cuff') {
    return [
      { key: 'roll_weight', label: 'Roll Weight', fmt: f3 },
      { key: 'total_qty', label: 'Total Qty' },
      { key: 'accepted_qty', label: 'Accepted Qty' },
      { key: 'rejected_qty', label: 'Rejected Qty' },
      { key: 'point_percentage', label: 'Rejection %', fmt: f2 },
      { key: 'grade', label: 'Grade' },
    ]
  }
  return [
    { key: 'roll_weight', label: 'Roll Weight', fmt: f3 },
    { key: 'gsm', label: 'GSM' },
    { key: 'width', label: 'Width' },
    { key: 'length_mtr', label: 'Length Mtr', fmt: f2 },
    { key: 'point_percentage', label: 'Point / 100 Per Sqm', fmt: f2 },
    { key: 'grade', label: 'Grade' },
  ]
})

const jcFetcher = async (txt) => (await api.lotReportJobCards(txt)).map(j => ({
  value: j.name, label: j.name,
  description: [j.work_order, j.production_item, j.color, `${j.custom_inspected_rolls} rolls`].filter(Boolean).join(' · '),
}))

async function load(name) {
  loading.value = true
  error.value = ''
  r.value = null
  try {
    r.value = await api.lotReport(name)
    jobCard.value = name
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function print(f) {
  format.value = f
  await nextTick()
  const prev = document.title
  document.title = `${h.value.report_no}-${f}`
  window.print()
  document.title = prev
}

onMounted(() => { if (route.query.jc) load(String(route.query.jc)) })
</script>

<style scoped>
.wide { max-width: 1100px !important; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
.report { background: #fff; border: 1px solid var(--slate-200); border-radius: 12px; padding: 16px; overflow-x: auto; color: #202124; }
.rep-title { text-align: center; font-weight: 800; font-size: 15px; margin-bottom: 10px; }
.sec-title { text-align: center; font-weight: 800; font-size: 12px; margin: 16px 0 8px; }
table { border-collapse: collapse; font-size: 11px; }
.hdr { width: 100%; }
.hdr th { text-align: left; font-weight: 700; padding: 4px 6px; border: 0.5px solid #cbd5e1; width: 16%; white-space: nowrap; }
.hdr td { padding: 4px 6px; border: 0.5px solid #cbd5e1; color: #5C7078; font-weight: 700; }
.chunk { margin-bottom: 12px; }
.chunk-head { font-size: 11px; margin-bottom: 4px; }
.grid { width: 100%; }
.grid th { background: #9AD4FD; color: #000; padding: 4px 6px; border: 0.5px solid #94a3b8; white-space: nowrap; }
.grid td { padding: 3px 6px; border: 0.5px solid #cbd5e1; color: #4B5C66; }
.grid .lbl { background: #F1F3F4; color: #202124; font-weight: 700; text-align: left; white-space: nowrap; }
.grid .num { text-align: right; }
.grid .b { font-weight: 700; }
.grid .tot td { font-weight: 800; color: #202124; background: #f8fafc; }
.grid .g3 { background: #E2116F; color: #000; font-weight: 800; }
.summary { max-width: 760px; margin: 0 auto; }
.sign { display: flex; justify-content: space-between; margin-top: 40px; font-size: 11px; font-weight: 700; padding: 0 40px; }

@media print {
  .no-print, :deep(.ah-header) { display: none !important; }
  .page-content { padding: 0 !important; max-width: none !important; }
  .report { border: none; padding: 0; overflow: visible; }
  .chunk { break-inside: avoid; }
  table { font-size: 8pt; }
}
</style>

<style>
@media print {
  @page { size: A4 portrait; margin: 10mm; }
  body, .page { background: #fff !important; }
  .status-banner { display: none !important; }
}
</style>
