<template>
  <div class="page">
    <AppHeader :title="'Roll ' + rollNo" :subtitle="(type === 'Collar Cuff' ? 'Collar / Cuff' : 'Fabric') + ' inspection'" active="inspection" :show-back="true" />
    <div class="page-content">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="loadError" class="alert alert-error">{{ loadError }}</div>
      <div v-if="info && !info.at_inspection" class="alert alert-warning">This roll is still at {{ info.current_process }} — inspecting it anyway.</div>
      <div v-if="info?.existing" class="alert alert-info">Already inspected ({{ info.existing.name }}) — saving updates it.</div>

      <template v-if="ready">
        <!-- Live result -->
        <div class="result card">
          <div class="result__grade" :class="'g' + calc.grade">{{ calc.grade }}</div>
          <div class="result__nums">
            <div><span>Points</span><b>{{ calc.total }}</b></div>
            <div><span>Points %</span><b>{{ fmt(calc.pct) }}</b></div>
            <div v-if="type === 'Fabric'"><span>Length</span><b>{{ fmt(calc.length) }} m</b></div>
            <div v-if="type === 'Fabric'"><span>Area</span><b>{{ fmt(calc.area) }} m²</b></div>
            <div v-if="type === 'Collar Cuff'"><span>Accepted</span><b>{{ calc.accepted }}</b></div>
            <div v-if="type === 'Collar Cuff'"><span>Rejected</span><b>{{ calc.total }}</b></div>
          </div>
        </div>

        <!-- Measurements -->
        <div class="card">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label">Roll Weight (kg)</label>
              <input v-model.number="f.roll_weight" type="number" step="0.001" class="form-input" />
            </div>
            <div class="form-group" v-if="type === 'Collar Cuff'">
              <label class="form-label">Total Qty (pcs)</label>
              <input v-model.number="f.total_qty" type="number" class="form-input" />
            </div>
            <template v-if="type === 'Fabric'">
              <div class="form-group">
                <label class="form-label">Actual Width (inch)</label>
                <input v-model.number="f.width" type="number" step="0.1" class="form-input" />
              </div>
              <div class="form-group">
                <label class="form-label">GSM</label>
                <input v-model.number="f.gsm" type="number" class="form-input" />
              </div>
              <div class="form-group">
                <label class="form-label">WPI Actual</label>
                <input v-model.number="f.wpi_actual" type="number" step="0.1" class="form-input" />
              </div>
              <div class="form-group">
                <label class="form-label">CPI Actual</label>
                <input v-model.number="f.cpi_actual" type="number" step="0.1" class="form-input" />
              </div>
            </template>
          </div>
        </div>

        <!-- Mistakes -->
        <div class="card">
          <div class="mk-head">
            <span class="section-title" style="border:none;margin:0;padding:0">Mistakes</span>
            <button class="btn btn-ghost mk-undo" :disabled="!history.length" @click="undo">↶ Undo</button>
          </div>
          <input v-model="mkFilter" class="form-input" placeholder="Filter mistakes" style="margin:10px 0" />
          <div class="mk" v-for="m in shownMistakes" :key="m.name" :class="{ 'mk--on': pts(m.name) > 0 }">
            <div class="mk__name">
              {{ m.name }}<span v-if="m.force_grade_3" class="badge badge-danger">G3</span>
              <span class="mk__pts" v-if="pts(m.name)">{{ pts(m.name) }} pts</span>
            </div>
            <div class="mk__btns">
              <button class="pt" @click="add(m.name, 'one_qty')">+1 <small>{{ q(m.name, 'one_qty') || '' }}</small></button>
              <button class="pt" @click="add(m.name, 'two_qty')">+2 <small>{{ q(m.name, 'two_qty') || '' }}</small></button>
              <button class="pt" @click="add(m.name, 'four_qty')">+4 <small>{{ q(m.name, 'four_qty') || '' }}</small></button>
              <input class="form-input len" type="number" min="0" placeholder="len"
                     :value="q(m.name, 'custom_points') || ''" @change="setLen(m.name, $event.target.value)" title="Length units ×4 points" />
            </div>
          </div>
        </div>

        <!-- Roll checks -->
        <div class="card">
          <button class="collapse" @click="showChecks = !showChecks">
            <span class="section-title" style="border:none;margin:0;padding:0">Roll checks</span><span>{{ showChecks ? '▲' : '▼' }}</span>
          </button>
          <div v-if="showChecks" style="margin-top:12px">
            <div class="grid-2">
              <div class="form-group" v-for="k in accKeys" :key="k.key">
                <label class="form-label">{{ k.label }}</label>
                <select v-model="f[k.key]" class="form-input"><option value=""></option><option v-for="o in ACC" :key="o">{{ o }}</option></select>
              </div>
              <div class="form-group" v-for="k in sevKeys" :key="k.key">
                <label class="form-label">{{ k.label }}</label>
                <select v-model="f[k.key]" class="form-input"><option>-</option><option>Mild</option><option>Heavy</option></select>
              </div>
              <div class="form-group"><label class="form-label">Inspection Machine</label><input v-model="f.machine_no" class="form-input" /></div>
              <div class="form-group"><label class="form-label">Dyeing Machine</label><input v-model="f.dyeing_machine" class="form-input" /></div>
              <div class="form-group"><label class="form-label">Dyeing Chamber</label><input v-model="f.dyeing_chamber_no" class="form-input" /></div>
              <div class="form-group"><label class="form-label">Sample</label><input v-model="f.sample" class="form-input" /></div>
              <div class="form-group"><label class="form-label">Scrap</label><input v-model="f.scrap" class="form-input" /></div>
            </div>
            <div class="form-group"><label class="form-label">Remarks</label><textarea v-model="f.remarks" class="form-input" rows="2"></textarea></div>
          </div>
        </div>

        <div class="card">
          <label class="chk"><input type="checkbox" v-model="f.direct" /> Direct (accepted as is)</label>
          <div class="form-group" style="margin-top:10px">
            <label class="form-label">Grade override</label>
            <select v-model="f.grade_override" class="form-input"><option value="">Use calculated ({{ calcGrade }})</option><option>1</option><option>2</option><option>3</option><option>Direct</option></select>
          </div>
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="saving" @click="save(false)">Save</button>
            <button class="btn btn-primary" :disabled="saving" @click="save(true)">{{ saving ? 'Saving…' : 'Save & next roll' }}</button>
          </div>
          <div v-if="saveError" class="alert alert-error" style="margin-top:10px">{{ saveError }}</div>
          <div v-if="saved" class="alert alert-success" style="margin-top:10px">{{ saved }}</div>
        </div>
      </template>
      <ScannerModal v-model="scannerOpen" title="Scan next roll" :allow-manual="true" @scanned="onNext" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
import { db } from '@/db'
import { callOrQueue } from '@/composables/useSync'
import { useAuthStore } from '@/stores/auth'
import { BASE, fmt, isPcs } from '@/utils'

const props = defineProps({ jobCard: String, rollNo: String })
const router = useRouter()
const auth = useAuthStore()
const ACC = ['Accepted', 'Cond Accepted', 'Not Accepted', 'Not Applicable']
const accKeys = [
  { key: 'approved_sample_checked', label: 'Approved Sample' }, { key: 'gold_seal_sample_checked', label: 'Gold Seal' },
  { key: 'shade_checked', label: 'Shade' }, { key: 'wicking', label: 'Wicking' },
]
const sevKeys = [
  { key: 'crow_feet', label: 'Crow Feet' }, { key: 'patta_problem', label: 'Patta Problem' },
  { key: 'vertical_line', label: 'Vertical Line' }, { key: 'rope_mark', label: 'Rope Mark' },
  { key: 'knurling', label: 'Knurling' }, { key: 'mild_snagging', label: 'Mild Snagging' },
]

const info = ref(null)
const loading = ref(false)
const loadError = ref('')
const mistakes = ref([])
const counts = reactive({})   // mistake -> { one_qty, two_qty, four_qty, custom_points }
const history = ref([])
const mkFilter = ref('')
const showChecks = ref(false)
const saving = ref(false)
const saveError = ref('')
const saved = ref('')
const scannerOpen = ref(false)
const ready = ref(false)
const type = ref('Fabric')
const LAST = 'PROD_INSP_LAST_' + props.jobCard

const f = reactive({
  roll_weight: null, width: null, gsm: null, wpi_actual: null, cpi_actual: null, total_qty: null,
  direct: false, grade_override: '', machine_no: '', dyeing_machine: '', dyeing_chamber_no: '',
  sample: '', scrap: '', remarks: '',
  approved_sample_checked: '', gold_seal_sample_checked: '', shade_checked: '', wicking: '',
  crow_feet: '-', patta_problem: '-', vertical_line: '-', rope_mark: '-', knurling: '-', mild_snagging: '-',
})

const q = (m, k) => counts[m]?.[k] || 0
function mk(name) { return mistakes.value.find(x => x.name === name) || { one_point: 1, two_point: 2, four_point: 4 } }
function pts(name) {
  const c = counts[name]
  if (!c) return 0
  const m = mk(name)
  return (c.one_qty || 0) * (m.one_point || 1) + (c.two_qty || 0) * (m.two_point || 2) +
         (c.four_qty || 0) * (m.four_point || 4) + (c.custom_points || 0) * 4
}
function add(name, key) {
  counts[name] = counts[name] || { one_qty: 0, two_qty: 0, four_qty: 0, custom_points: 0 }
  counts[name][key] += 1
  history.value.push({ name, key })
}
function setLen(name, v) {
  counts[name] = counts[name] || { one_qty: 0, two_qty: 0, four_qty: 0, custom_points: 0 }
  counts[name].custom_points = Math.max(0, parseInt(v || 0, 10) || 0)
}
function undo() {
  const h = history.value.pop()
  if (h && counts[h.name] && counts[h.name][h.key] > 0) counts[h.name][h.key] -= 1
}

const shownMistakes = computed(() => {
  const s = mkFilter.value.trim().toLowerCase()
  const list = mistakes.value.filter(m => !s || m.name.toLowerCase().includes(s))
  // active mistakes first
  return [...list.filter(m => pts(m.name) > 0), ...list.filter(m => !pts(m.name))]
})

const calc = computed(() => {
  const total = mistakes.value.reduce((s, m) => s + pts(m.name), 0) +
    Object.keys(counts).filter(k => !mistakes.value.some(m => m.name === k)).reduce((s, k) => s + pts(k), 0)
  const force3 = mistakes.value.some(m => m.force_grade_3 && pts(m.name) > 0)
  let pct = 0, length = 0, area = 0, accepted = 0
  if (type.value === 'Collar Cuff') {
    const tq = Number(f.total_qty) || 0
    pct = tq ? total / tq * 100 : 0
    accepted = Math.max(0, tq - total)
  } else {
    const wcm = (Number(f.width) || 0) * 2.54
    const gpm = wcm / 100 * (Number(f.gsm) || 0)
    if (gpm > 0 && Number(f.roll_weight) > 0) {
      length = Number(f.roll_weight) / gpm * 1000
      area = length * wcm / 100
    }
    pct = area ? total / area * 100 : 0
  }
  const g3 = auth.settings.grade_3_min_points || 100
  const g2 = auth.settings.grade_2_min_points || 40
  let grade = (force3 || pct > g3) ? '3' : (pct >= g2 ? '2' : (f.direct ? 'Direct' : '1'))
  const calcGradeVal = grade
  if (f.grade_override) grade = f.grade_override
  return { total, pct, length, area, accepted, grade, calcGrade: calcGradeVal }
})
const calcGrade = computed(() => calc.value.calcGrade)

async function loadMistakes() {
  try {
    mistakes.value = await api.mistakes(type.value)
    await db.mistakes.put({ key: type.value, inspection_type: type.value, rows: mistakes.value })
  } catch {
    const cached = await db.mistakes.get(type.value)
    mistakes.value = cached?.rows || []
  }
}

function applyExisting(e) {
  for (const k of Object.keys(f)) if (e[k] !== undefined && e[k] !== null) f[k] = k === 'direct' ? !!e[k] : e[k]
  for (const m of e.mistakes || []) {
    counts[m.mistake] = { one_qty: m.one_qty || 0, two_qty: m.two_qty || 0, four_qty: m.four_qty || 0, custom_points: m.custom_points || 0 }
  }
}

async function load() {
  loading.value = true
  ready.value = false
  loadError.value = ''
  saved.value = ''
  Object.keys(counts).forEach(k => delete counts[k])
  history.value = []
  const last = JSON.parse(localStorage.getItem(LAST) || '{}')
  try {
    info.value = await api.rollForInspection(props.jobCard, props.rollNo)
    type.value = info.value.inspection_type
    f.roll_weight = info.value.roll_weight
    f.total_qty = info.value.total_qty || null
    f.gsm = last.gsm || info.value.default_gsm || null
    f.width = last.width || null
    f.machine_no = last.machine_no || ''
    f.dyeing_machine = last.dyeing_machine || ''
    if (info.value.existing) applyExisting(info.value.existing)
  } catch (err) {
    // offline: fall back to the cached inspection context
    const ctx = JSON.parse(localStorage.getItem('PROD_INSP_CTX_' + props.jobCard) || 'null')
    const r = ctx?.rolls?.find(x => x.name === props.rollNo)
    if (!r) { loadError.value = err.message; loading.value = false; return }
    info.value = { at_inspection: r.at_inspection, current_process: r.current_process, existing: null }
    type.value = isPcs(r.stock_uom) ? 'Collar Cuff' : 'Fabric'
    f.roll_weight = r.current_weight || r.roll_weight
    f.total_qty = r.total_qty || null
    f.gsm = last.gsm || ctx.work_order?.required_gsm || null
    f.width = last.width || null
  }
  await loadMistakes()
  loading.value = false
  ready.value = true
}

function payload() {
  const data = { ...f, direct: f.direct ? 1 : 0, inspection_type: type.value, inspected_on: undefined }
  data.mistakes = Object.entries(counts)
    .filter(([name]) => pts(name) > 0)
    .map(([mistake, c]) => ({ mistake, ...c }))
  return data
}

async function save(next) {
  saving.value = true
  saveError.value = ''
  saved.value = ''
  try {
    localStorage.setItem(LAST, JSON.stringify({ gsm: f.gsm, width: f.width, machine_no: f.machine_no, dyeing_machine: f.dyeing_machine }))
    const r = await callOrQueue('pranera_production.api.inspection.save_roll_inspection',
      { job_card: props.jobCard, roll_no: props.rollNo, data: payload() }, `Inspection ${props.rollNo}`)
    // reflect in the cached job-card context so the list shows it even offline
    const key = 'PROD_INSP_CTX_' + props.jobCard
    const ctx = JSON.parse(localStorage.getItem(key) || 'null')
    const row = ctx?.rolls?.find(x => x.name === props.rollNo)
    if (row) {
      row.inspection = { name: r?.name || 'queued', grade: r?.grade || calc.value.grade,
                         point_percentage: r?.point_percentage ?? calc.value.pct, roll_weight: f.roll_weight }
      localStorage.setItem(key, JSON.stringify(ctx))
    }
    saved.value = r?.queued ? 'Saved offline — will sync automatically' : `Saved ${r.name} · Grade ${r.grade}`
    if (next) scannerOpen.value = true
  } catch (err) {
    saveError.value = err.message
  } finally {
    saving.value = false
  }
}

function onNext(text) {
  const parts = String(text).split('#')
  const rn = parts.length >= 3 ? parts[parts.length - 1] : String(text).trim()
  router.replace(BASE + '/inspection/' + encodeURIComponent(props.jobCard) + '/roll/' + encodeURIComponent(rn))
}

watch(() => props.rollNo, load)
onMounted(load)
</script>

<style scoped>
.result { display: flex; gap: 14px; align-items: center; position: sticky; top: 64px; z-index: 20; }
.result__grade { width: 64px; height: 64px; border-radius: 14px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; color: #fff; background: #16a34a; flex-shrink: 0; }
.result__grade.g2 { background: #d97706; }
.result__grade.g3 { background: #dc2626; }
.result__grade.gDirect { background: #2563eb; font-size: 14px; }
.result__nums { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 14px; flex: 1; }
.result__nums div { display: flex; justify-content: space-between; font-size: 12px; color: var(--slate-500); }
.result__nums b { color: var(--slate-900); font-size: 14px; }
.mk-head { display: flex; justify-content: space-between; align-items: center; }
.mk-undo { padding: 6px 12px; }
.mk { padding: 8px 0; border-bottom: 1px solid var(--slate-100); }
.mk--on { background: #fff7ed; margin: 0 -8px; padding: 8px; border-radius: 8px; }
.mk__name { font-size: 13px; font-weight: 600; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.mk__pts { margin-left: auto; font-weight: 800; color: #c2410c; }
.mk__btns { display: flex; gap: 6px; margin-top: 6px; }
.pt { flex: 1; border: 1.5px solid var(--slate-200); background: #fff; border-radius: 8px; padding: 9px 4px; font-weight: 800; font-size: 14px; }
.pt:active { background: var(--slate-100); }
.pt small { color: #c2410c; font-weight: 800; }
.len { width: 64px; flex: 0 0 64px; padding: 8px; }
.collapse { display: flex; justify-content: space-between; align-items: center; width: 100%; border: none; background: none; padding: 0; }
.chk { display: flex; gap: 8px; align-items: center; font-size: 14px; font-weight: 600; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
</style>
