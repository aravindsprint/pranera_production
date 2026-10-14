<template>
  <div class="page">
    <AppHeader title="Inspection" :subtitle="jobCard" active="inspection" :show-back="true" />
    <div class="page-content">
      <div v-if="offline" class="alert alert-warning">Offline — working from the last loaded data. Roll saves will sync later.</div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <template v-if="ctx">
        <div class="card">
          <div class="h">{{ ctx.work_order.production_item }}</div>
          <div class="sub">{{ ctx.work_order.item_name }}</div>
          <div class="sub">{{ ctx.job_card.work_order }} · {{ ctx.job_card.workstation }} · {{ ctx.inspection_type }}</div>
          <div class="sub" v-if="ctx.work_order.color">{{ ctx.work_order.color }} · width {{ ctx.work_order.width }} · GSM {{ ctx.work_order.required_gsm }}</div>
        </div>

        <button class="btn btn-primary btn-full btn-lg" style="margin-bottom:12px" @click="scannerOpen = true">📷 Scan roll to inspect</button>
        <div v-if="scanError" class="alert alert-error">{{ scanError }}</div>

        <!-- Lot checks -->
        <div class="card">
          <button class="collapse" @click="showLot = !showLot">
            <span class="section-title" style="border:none;margin:0;padding:0">Lot checks</span>
            <span>{{ showLot ? '▲' : '▼' }}</span>
          </button>
          <div v-if="showLot" class="lot">
            <div class="grid-2">
              <div v-for="f in numFields" :key="f.key" class="form-group">
                <label class="form-label">{{ f.label }}</label>
                <input v-model="lot[f.key]" :type="f.type || 'number'" step="0.01" class="form-input" />
              </div>
            </div>
            <div class="grid-2">
              <div v-for="f in accFields" :key="f.key" class="form-group">
                <label class="form-label">{{ f.label }}</label>
                <select v-model="lot[f.key]" class="form-input">
                  <option value=""></option>
                  <option v-for="o in ACC" :key="o">{{ o }}</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Inspect Approval</label>
                <select v-model="lot.custom_inspect_approval" class="form-input">
                  <option value=""></option><option>Ok</option><option>Not Ok</option>
                </select>
              </div>
            </div>
            <button class="btn btn-outline btn-full" :disabled="savingLot" @click="saveLot">{{ savingLot ? 'Saving…' : 'Save lot checks' }}</button>
            <div v-if="lotMsg" class="hint">{{ lotMsg }}</div>
          </div>
        </div>

        <!-- Summary -->
        <div class="card" v-if="ctx.job_card.summary.grades.length">
          <div class="section-title">Summary — {{ ctx.job_card.summary.rolls }} rolls · {{ fmt(ctx.job_card.summary.weight) }} kg · avg {{ fmt(ctx.job_card.summary.avg_points_percentage) }}%</div>
          <div class="grade-row" v-for="g in ctx.job_card.summary.grades" :key="g.grade">
            <span class="badge" :class="gradeClass(g.grade)">Grade {{ g.grade }}</span>
            <span>{{ g.no_of_rolls }} rolls</span>
            <span>{{ fmt(g.weight) }} kg</span>
            <span>{{ fmt(g.percentage) }}%</span>
          </div>
        </div>

        <!-- Rolls -->
        <div class="card">
          <div class="section-title">Rolls ({{ inspectedCount }}/{{ ctx.rolls.length }} inspected)</div>
          <div class="roll" v-for="r in ctx.rolls" :key="r.name" @click="openRoll(r.name)">
            <div class="roll__body">
              <div class="roll__no">{{ r.name }}
                <span v-if="!r.at_inspection" class="badge badge-secondary">{{ r.current_process }}</span>
              </div>
              <div class="roll__meta">{{ fmt(r.current_weight || r.roll_weight, 3) }} kg<span v-if="r.total_qty"> · {{ r.total_qty }} pcs</span><span v-if="r.knitting_machine_no"> · {{ r.knitting_machine_no }}</span></div>
            </div>
            <template v-if="r.inspection">
              <span class="badge" :class="gradeClass(r.inspection.grade)">G{{ r.inspection.grade }}</span>
              <span class="roll__pts">{{ fmt(r.inspection.point_percentage) }}%</span>
            </template>
            <span v-else class="roll__todo">Inspect ›</span>
          </div>
        </div>

        <button v-if="inspectedCount" class="btn btn-outline btn-full" style="margin-bottom:12px"
                @click="router.push({ path: BASE + '/lot-report', query: { jc: jobCard } })">🧾 Lot Inspection Report / PDF</button>

        <div class="card" v-if="ctx.job_card.docstatus === 0">
          <button class="btn btn-primary btn-full" :disabled="completing || !inspectedCount" @click="complete">
            {{ completing ? 'Completing…' : 'Inspection done — complete Job Card' }}
          </button>
          <div class="hint">Submits the INSPECTION Job Card so the MF can be made. Uninspected rolls: {{ ctx.rolls.length - inspectedCount }}.</div>
          <div v-if="completeError" class="alert alert-error" style="margin-top:8px">{{ completeError }}</div>
        </div>
      </template>
      <ScannerModal v-model="scannerOpen" title="Scan roll" :allow-manual="true" @scanned="onScanned" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
import { db } from '@/db'
import { BASE, fmt, gradeClass } from '@/utils'

const props = defineProps({ jobCard: String })
const router = useRouter()
const ACC = ['Accepted', 'Cond Accepted', 'Not Accepted', 'Not Applicable']
const numFields = [
  { key: 'custom_fabric_required_width', label: 'Required Width', type: 'text' },
  { key: 'custom_fabric_required_gsm', label: 'Required GSM' },
  { key: 'custom_wpi', label: 'WPI' }, { key: 'custom_wpi_actual', label: 'WPI Actual' },
  { key: 'custom_cpi', label: 'CPI' }, { key: 'custom_cpi_actual', label: 'CPI Actual' },
]
const accFields = [
  { key: 'custom_approved_sample_checked', label: 'Approved Sample' },
  { key: 'custom_gold_seal_sample_checked', label: 'Gold Seal Sample' },
  { key: 'custom_shade', label: 'Shade' },
  { key: 'custom_within_roll_shade_variation', label: 'Within Roll Shade' },
  { key: 'custom_roll_to_roll_shade_variation', label: 'Roll to Roll Shade' },
  { key: 'custom_csv', label: 'CSV' },
  { key: 'custom_hand_feel', label: 'Hand Feel' },
  { key: 'custom_length_stretch', label: 'Length Stretch' },
  { key: 'custom_width_stretch', label: 'Width Stretch' },
  { key: 'custom_design', label: 'Design' },
  { key: 'custom_testing', label: 'Testing' },
]

const CACHE = () => 'PROD_INSP_CTX_' + props.jobCard
const ctx = ref(JSON.parse(localStorage.getItem(CACHE()) || 'null'))
const loading = ref(false)
const error = ref('')
const offline = ref(false)
const lot = reactive({})
const showLot = ref(false)
const savingLot = ref(false)
const lotMsg = ref('')
const scannerOpen = ref(false)
const scanError = ref('')
const completing = ref(false)
const completeError = ref('')

const inspectedCount = computed(() => (ctx.value?.rolls || []).filter(r => r.inspection).length)

function fillLot() {
  Object.assign(lot, ctx.value?.job_card?.lot || {})
}

async function load() {
  loading.value = !ctx.value
  try {
    ctx.value = await api.inspectionContext(props.jobCard)
    localStorage.setItem(CACHE(), JSON.stringify(ctx.value))
    await db.mistakes.put({ key: ctx.value.inspection_type, inspection_type: ctx.value.inspection_type, rows: ctx.value.mistakes })
    offline.value = false
  } catch (err) {
    if (!ctx.value) error.value = err.message
    offline.value = true
  } finally {
    loading.value = false
    fillLot()
  }
}

async function saveLot() {
  savingLot.value = true
  lotMsg.value = ''
  try { await api.saveLotChecks(props.jobCard, { ...lot }); lotMsg.value = 'Saved' } catch (err) { lotMsg.value = err.message }
  savingLot.value = false
}

function openRoll(rollNo) {
  router.push(BASE + '/inspection/' + encodeURIComponent(props.jobCard) + '/roll/' + encodeURIComponent(rollNo))
}

function onScanned(text) {
  scanError.value = ''
  const parts = String(text).split('#')
  const rn = parts.length >= 3 ? parts[parts.length - 1] : String(text).trim()
  if (ctx.value && !ctx.value.rolls.some(r => r.name === rn)) {
    scanError.value = `Roll ${rn} is not in process for ${ctx.value.job_card.work_order}`
    return
  }
  openRoll(rn)
}

async function complete() {
  completing.value = true
  completeError.value = ''
  try {
    await api.markInspectionComplete(props.jobCard)
    await api.completeJobCard(props.jobCard, null, 1)
    await load()
  } catch (err) {
    completeError.value = err.message
  } finally {
    completing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.h { font-weight: 800; overflow-wrap: anywhere; }
.sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.collapse { display: flex; justify-content: space-between; align-items: center; width: 100%; border: none; background: none; padding: 0; }
.lot { margin-top: 12px; }
.grade-row { display: flex; gap: 12px; align-items: center; font-size: 13px; padding: 6px 0; }
.roll { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--slate-100); cursor: pointer; }
.roll__body { flex: 1; min-width: 0; }
.roll__no { font-weight: 700; display: flex; gap: 6px; align-items: center; }
.roll__meta { font-size: 11px; color: var(--slate-500); }
.roll__pts { font-size: 12px; font-weight: 700; min-width: 54px; text-align: right; }
.roll__todo { font-size: 12px; font-weight: 700; color: var(--app-primary); }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
</style>
