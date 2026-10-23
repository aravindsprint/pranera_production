<template>
  <div class="page">
    <AppHeader :title="'Roll ' + rollNo" :subtitle="(type === 'Collar Cuff' ? 'Collar / Cuff' : 'Fabric') + ' inspection · ' + (step === 1 ? 'Mistakes' : 'Roll details')" active="inspection" :show-back="true" />
    <div class="page-content" :class="{ 'ri-wide': step === 1 }">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="loadError" class="alert alert-error">{{ loadError }}</div>
      <div v-if="info && !info.at_inspection" class="alert alert-warning">This roll is still at {{ info.current_process }} — inspecting it anyway.</div>
      <div v-if="info?.existing" class="alert alert-info">Already inspected ({{ info.existing.name }}) — saving updates it.</div>

      <template v-if="ready">
        <!-- ───────── Step 1: mistakes (same board as the Ionic app) ───────── -->
        <template v-if="step === 1">
          <div class="mbar card">
            <div class="mbar__roll">
              <div><span>Roll No</span><b>{{ rollNo }}</b></div>
              <div v-if="info?.greige_roll_no && info.greige_roll_no !== rollNo"><span>Greige Roll</span><b>{{ info.greige_roll_no }}</b></div>
            </div>
            <button class="mbtn mbtn--toggle" @click="board = board === 'main' ? 'other' : 'main'">
              {{ board === 'main' ? 'Other' : 'Main' }}<br />Mistakes
            </button>
            <div class="mbar__actions">
              <span class="mbtn mbtn--total">Total Points : {{ calc.total }}</span>
              <button class="mbtn mbtn--blue" :disabled="!history.length" @click="undo">Undo</button>
              <button class="mbtn mbtn--green" @click="summaryOpen = true">Summary</button>
              <button class="mbtn mbtn--blue" @click="goStep(2)">Next →</button>
            </div>
          </div>

          <div v-if="!mistakes.length" class="alert alert-warning">
            No Inspection Mistakes on this site. Run <code>bench migrate</code> (they ship with the app).
          </div>

          <div v-else-if="!boardCols.length" class="alert alert-info">
            No mistakes are set to show on the {{ board === 'main' ? 'Main' : 'Other' }} board. Set Board / Column / Show on Board in Inspection Mistake (desk).
          </div>
          <div class="board" v-else>
            <div class="board__col" v-for="(col, ci) in boardCols" :key="board + ci">
              <button v-for="t in col" :key="t.name" class="tile" :style="{ background: t.color, height: t.h + 'cqw' }"
                      @click="tap(t)">
                <span class="tile__name">{{ t.name }}</span>
                <span class="tile__info" v-if="t.pt === 'len'">Mistake Point : {{ pts(t.name) }}</span>
                <span class="tile__info" v-else>Count : {{ q(t.name, KEY[t.pt]) }}<br />Point : {{ t.pt }}</span>
              </button>
            </div>
          </div>
        </template>

        <!-- ───────── Step 2: roll details, checks, grade ───────── -->
        <template v-else>
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
            <button class="btn btn-outline back1" @click="goStep(1)">← Mistakes</button>
          </div>

          <div class="card">
            <div class="section-title">Roll details</div>
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

          <div class="card">
            <div class="section-title">Roll checks</div>
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
      </template>

      <!-- Length (Mtr) modal for metre-based mistakes -->
      <div v-if="lenTile" class="ov" @click.self="lenTile = null">
        <div class="ov__box">
          <div class="ov__title">{{ lenTile.name }}</div>
          <div class="ov__label">Enter the Mtr</div>
          <div class="ov__counter">
            <button class="ov__pm" @click="lenVal = Math.max(0, (Number(lenVal) || 0) - 1)">−</button>
            <input v-model.number="lenVal" type="number" min="0" class="ov__num" @keyup.enter="applyLen" ref="lenInput" />
            <button class="ov__pm" @click="lenVal = (Number(lenVal) || 0) + 1">+</button>
          </div>
          <div class="ov__hint">{{ (Number(lenVal) || 0) * 4 }} points</div>
          <button class="btn btn-primary btn-full btn-lg" @click="applyLen">Submit</button>
        </div>
      </div>

      <!-- Summary -->
      <div v-if="summaryOpen" class="ov" @click.self="summaryOpen = false">
        <div class="ov__box ov__box--wide">
          <div class="ov__title">Roll {{ rollNo }} — mistakes</div>
          <table class="sum" v-if="summaryRows.length">
            <thead><tr><th>Mistake</th><th>1 pt</th><th>2 pt</th><th>4 pt</th><th>Mtr</th><th>Points</th></tr></thead>
            <tbody>
              <tr v-for="r in summaryRows" :key="r.name">
                <td>{{ r.name }}</td><td>{{ r.one_qty || '' }}</td><td>{{ r.two_qty || '' }}</td>
                <td>{{ r.four_qty || '' }}</td><td>{{ r.custom_points || '' }}</td><td><b>{{ r.points }}</b></td>
              </tr>
            </tbody>
            <tfoot><tr><td colspan="5">Total</td><td><b>{{ calc.total }}</b></td></tr></tfoot>
          </table>
          <div v-else class="muted">No mistakes yet.</div>
          <button class="btn btn-outline btn-full" style="margin-top:12px" @click="summaryOpen = false">Close</button>
        </div>
      </div>

      <ScannerModal v-model="scannerOpen" title="Scan next roll" :allow-manual="true" @scanned="onNext" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
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

// The board comes from Inspection Mistake in the desk: Show on Board, Board
// (Main/Other), Column, Sequence (order in the column), Tap Adds (1/2/4 or
// Metre = enter metres, 4 points each), Tile Colour and Tile Height (% of
// the board width).
const FALLBACK_COLOURS = ['#1B4F72', '#159274', '#784213', '#d279a6', '#e65c00', '#512E5F', '#707D7E', '#0f766e']
const KEY = { 1: 'one_qty', 2: 'two_qty', 4: 'four_qty', len: 'custom_points' }

const step = ref(1)
const board = ref('main')
const summaryOpen = ref(false)
const lenTile = ref(null)
const lenVal = ref(0)
const lenInput = ref(null)

const info = ref(null)
const loading = ref(false)
const loadError = ref('')
const mistakes = ref([])
const counts = reactive({})   // mistake -> { one_qty, two_qty, four_qty, custom_points }
const history = ref([])
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
function ensure(name) {
  counts[name] = counts[name] || { one_qty: 0, two_qty: 0, four_qty: 0, custom_points: 0 }
  return counts[name]
}
function add(name, key) {
  ensure(name)[key] += 1
  history.value.push({ name, key })
}
function undo() {
  const h = history.value.pop()
  if (!h || !counts[h.name]) return
  if (h.key === 'custom_points') counts[h.name].custom_points = h.prev
  else if (counts[h.name][h.key] > 0) counts[h.name][h.key] -= 1
}
async function tap(t) {
  if (t.pt !== 'len') return add(t.name, KEY[t.pt])
  lenTile.value = t
  lenVal.value = 0
  await nextTick()
  lenInput.value?.focus()
}
function applyLen() {
  const t = lenTile.value
  const v = Math.max(0, parseInt(lenVal.value || 0, 10) || 0)
  const c = ensure(t.name)
  history.value.push({ name: t.name, key: 'custom_points', prev: c.custom_points })
  c.custom_points = v   // like the Ionic app: the entered metres replace the previous value
  lenTile.value = null
}
function goStep(n) {
  step.value = n
  window.scrollTo({ top: 0 })
}

const boardCols = computed(() => {
  const cols = {}
  mistakes.value.forEach((m, i) => {
    if (m.show_on_board === 0) return
    if ((m.board || 'Other') !== (board.value === 'main' ? 'Main' : 'Other')) return
    const c = Number(m.column_no) || 1
    ;(cols[c] = cols[c] || []).push({
      name: m.name, seq: Number(m.sequence) || 0,
      pt: m.tile_point === 'Metre' ? 'len' : Number(m.tile_point || 4),
      color: m.tile_color || FALLBACK_COLOURS[i % FALLBACK_COLOURS.length],
      h: Number(m.tile_height) || 11,
    })
  })
  return Object.keys(cols).map(Number).sort((x, y) => x - y)
    .map(k => cols[k].sort((x, y) => x.seq - y.seq || x.name.localeCompare(y.name)))
})

const summaryRows = computed(() => Object.entries(counts)
  .map(([name, c]) => ({ name, ...c, points: pts(name) }))
  .filter(r => r.points > 0))


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
  let rows
  try {
    rows = await api.mistakes(type.value)
  } catch {
    const cached = await db.mistakes.get(type.value).catch(() => null)
    mistakes.value = cached?.rows || []
    return
  }
  mistakes.value = rows
  // cache for offline use — store the plain array (IndexedDB can't clone Vue proxies)
  db.mistakes.put({ key: type.value, inspection_type: type.value, rows: JSON.parse(JSON.stringify(rows)) }).catch(() => {})
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
  step.value = 1
  board.value = 'main'
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
.ri-wide { max-width: 1400px !important; }
/* Step 1 bar */
.mbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 10px 12px; }
.mbar__roll { display: flex; gap: 14px; }
.mbar__roll div { display: flex; flex-direction: column; border: 1px solid var(--slate-200); border-radius: 8px; padding: 4px 12px; min-width: 110px; }
.mbar__roll span { font-size: 11px; color: var(--slate-500); }
.mbar__roll b { font-size: 18px; }
.mbar__actions { display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.mbtn { border: none; border-radius: 8px; padding: 12px 16px; font-weight: 700; font-size: 15px; color: #fff; line-height: 1.15; }
.mbtn:disabled { opacity: .5; }
.mbtn--toggle { background: #3880ff; min-height: 56px; }
.mbtn--total { background: #eb445a; display: inline-flex; align-items: center; }
.mbtn--blue { background: #3880ff; }
.mbtn--green { background: #2dd36f; }
/* Board: tile heights are % of the board width (cqw), like the Ionic vw sizes */
.board { container-type: inline-size; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 0; margin-bottom: 16px; }
.board__col { display: flex; flex-direction: column; min-width: 0; }
.tile { border: 5px solid #fff; border-radius: 10px; color: #fff; font-weight: 700; text-align: center;
        display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
        padding: 4px; min-height: 64px; cursor: pointer; user-select: none; overflow: hidden; }
.tile:active { filter: brightness(1.15); transform: scale(.98); }
.tile__name { font-size: clamp(12px, 1.7cqw, 24px); line-height: 1.15; overflow-wrap: anywhere; }
.tile__info { font-size: clamp(10px, 1.1cqw, 15px); font-weight: 600; opacity: .95; }
/* overlays */
.ov { position: fixed; inset: 0; background: rgba(15,23,42,.55); z-index: 200; display: flex; align-items: center; justify-content: center; padding: 16px; }
.ov__box { background: #fff; border-radius: 14px; padding: 20px; width: 100%; max-width: 380px; }
.ov__box--wide { max-width: 640px; max-height: 85vh; overflow: auto; }
.ov__title { font-size: 18px; font-weight: 800; margin-bottom: 12px; }
.ov__label { font-weight: 700; text-align: center; margin-bottom: 8px; }
.ov__counter { display: flex; gap: 8px; align-items: center; }
.ov__pm { width: 56px; height: 56px; border: none; border-radius: 10px; background: #eb445a; color: #fff; font-size: 26px; font-weight: 800; }
.ov__num { flex: 1; min-width: 0; height: 56px; text-align: center; font-size: 24px; font-weight: 800; border: 1px solid var(--slate-200); border-radius: 10px; }
.ov__hint { text-align: center; color: var(--slate-500); margin: 8px 0 14px; }
.sum { width: 100%; border-collapse: collapse; font-size: 14px; }
.sum th, .sum td { padding: 6px 8px; border-bottom: 1px solid var(--slate-100); text-align: right; }
.sum th:first-child, .sum td:first-child { text-align: left; }
.sum tfoot td { border-top: 2px solid var(--slate-200); }
.muted { color: var(--slate-500); }
/* Step 2 */
.back1 { align-self: flex-start; padding: 8px 12px; }
@media (max-width: 700px) {
  .board { grid-auto-flow: row; grid-template-columns: repeat(2, 1fr); }
  .board__col { display: contents; }
  .tile { height: auto !important; min-height: 76px; }
  .tile__name { font-size: 14px; } .tile__info { font-size: 11px; }
}
.result { display: flex; gap: 14px; align-items: center; position: sticky; top: 64px; z-index: 20; }
.result__grade { width: 64px; height: 64px; border-radius: 14px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; color: #fff; background: #16a34a; flex-shrink: 0; }
.result__grade.g2 { background: #d97706; }
.result__grade.g3 { background: #dc2626; }
.result__grade.gDirect { background: #2563eb; font-size: 14px; }
.result__nums { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 14px; flex: 1; }
.result__nums div { display: flex; justify-content: space-between; font-size: 12px; color: var(--slate-500); }
.result__nums b { color: var(--slate-900); font-size: 14px; }
.chk { display: flex; gap: 8px; align-items: center; font-size: 14px; font-weight: 600; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
</style>
