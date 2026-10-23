<template>
  <div class="page">
    <AppHeader title="Dye Chart" :subtitle="jobCard" active="job-cards" :show-back="true" />
    <div class="page-content dc-wide">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <div v-if="offlineAt" class="alert alert-warning">Offline — showing this Dye Chart as of {{ new Date(offlineAt).toLocaleString() }}. Additions are saved on this device and issued when the connection is back.</div>
      <div v-if="pendingMsg" class="alert alert-info">{{ pendingMsg }}</div>

      <template v-if="ctx">
        <!-- Job Card -->
        <div class="card">
          <div class="row-top">
            <b>{{ ctx.job_card.operation }} · {{ ctx.job_card.workstation }}</b>
            <span class="badge" :class="statusClass(ctx.job_card.status)">{{ ctx.job_card.status }}</span>
          </div>
          <div class="sub">{{ ctx.job_card.work_order }} · {{ ctx.job_card.production_item }}</div>
          <div class="sub">Qty {{ fmt(ctx.job_card.for_quantity, 3) }}<span v-if="ctx.job_card.add_on_qty"> + add-on {{ fmt(ctx.job_card.add_on_qty, 3) }}</span> kg</div>
          <div v-if="ctx.job_card.running" class="alert alert-info" style="margin-top:10px">▶ Job Card is running — chemical additions are open.</div>
        </div>

        <!-- Dye Chart: edit -->
        <div class="card" v-if="editable">
          <div class="section-title">{{ ctx.dye_chart ? 'Dye Chart ' + ctx.dye_chart.name + ' (draft)' : 'New Dye Chart' }}</div>
          <label class="form-label">Dye Receipe</label>
          <AsyncSelect v-model="recipe" :fetcher="recipeFetcher" placeholder="Search recipe (this item's first)" @select="o => o && loadRecipe(o.value)" />
          <div v-if="!ctx.dye_chart && ctx.suggested_recipe" class="hint">Loaded {{ ctx.suggested_recipe }}, the {{ ctx.job_card.production_item }} recipe. Pick another to replace it.</div>
          <div v-else-if="!ctx.dye_chart && !ctx.suggested_recipe" class="alert alert-warning" style="margin-top:8px">No Dye Receipe for {{ ctx.job_card.production_item }} — search another item's recipe or add the lines by hand.</div>
          <label class="form-label" style="margin-top:12px">Lot weight (kg)</label>
          <input v-model.number="lotWeight" type="number" step="0.001" class="form-input" />
          <div class="hint">Job Card qty + add-on qty. Totals: % → lot × dosage ÷ 100 · GPL → lot × dosage ÷ 1000 × MLR.</div>

          <div class="lt">
            <div class="lt__row lt__head">
              <span>No.</span><span>Bath no</span><span>MLR</span><span>Function</span><span>Item</span>
              <span class="r">Dosage</span><span>UOM</span><span class="r">Total (kg)</span><span></span>
            </div>
            <div class="lt__row" v-for="(l, i) in lines" :key="i">
              <span class="lt__no"><i class="cl">No.</i>{{ i + 1 }}</span>
              <label><i class="cl">Bath no</i><input v-model="l.bath_no" class="form-input" /></label>
              <label><i class="cl">MLR</i><input v-model="l.mlr" class="form-input" /></label>
              <label><i class="cl">Function</i><input v-model="l.chemicals" class="form-input" list="dye-functions" /></label>
              <label class="lt__item"><i class="cl">Item</i><AsyncSelect v-model="l.item" :fetcher="itemFetcher" placeholder="Chemical item" /></label>
              <label><i class="cl">Dosage</i><input v-model.number="l.dosage" type="number" step="0.0001" class="form-input r" /></label>
              <label><i class="cl">UOM</i><select v-model="l.uom" class="form-input"><option>Percentage</option><option>GPL</option></select></label>
              <span class="lt__total"><i class="cl">Total (kg)</i>{{ fmt(lineTotal(l), 3) }}</span>
              <button class="x" title="Remove line" @click="lines.splice(i, 1)">✕</button>
            </div>
            <datalist id="dye-functions"><option v-for="f in FUNCTIONS" :key="f" :value="f" /></datalist>
          </div>
          <button class="btn btn-ghost" @click="lines.push({ bath_no: lines.at(-1)?.bath_no || '1', mlr: lines.at(-1)?.mlr || '', chemicals: '', item: '', dosage: null, uom: 'Percentage' })">+ Line</button>
          <div class="totals">Total chemicals <b>{{ fmt(lines.reduce((s, l) => s + lineTotal(l), 0), 3) }} kg</b> · {{ lines.length }} lines</div>
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="saving" @click="save(false)">Save draft</button>
            <button class="btn btn-primary" :disabled="saving" @click="save(true)">{{ saving ? 'Saving…' : 'Save & Submit' }}</button>
          </div>
          <div v-if="saveMsg" class="alert" :class="saveOk ? 'alert-success' : 'alert-error'" style="margin-top:10px">{{ saveMsg }}</div>
        </div>

        <!-- Dye Chart: submitted -->
        <div class="card" v-else-if="ctx.dye_chart">
          <div class="row-top">
            <b>Dye Chart {{ ctx.dye_chart.name }}</b>
            <span class="badge" :class="ctx.dye_chart.docstatus === 1 ? 'badge-success' : 'badge-warning'">{{ ctx.dye_chart.docstatus === 1 ? 'Submitted' : 'Draft' }}</span>
          </div>
          <div class="sub">Recipe {{ ctx.dye_chart.dye_receipe || '—' }} · lot {{ fmt(ctx.dye_chart.lot_weight, 3) }} kg</div>
          <div class="lt lt--ro">
            <div class="lt__row lt__head">
              <span>No.</span><span>Bath no</span><span>MLR</span><span>Function</span><span>Item</span>
              <span class="r">Dosage</span><span>UOM</span><span class="r">Total (kg)</span><span></span>
            </div>
            <div class="lt__row" v-for="(l, i) in ctx.lines" :key="l.name">
              <span class="lt__no"><i class="cl">No.</i>{{ i + 1 }}</span>
              <span><i class="cl">Bath no</i>{{ l.bath_no || '-' }}</span>
              <span><i class="cl">MLR</i>{{ l.mlr || '-' }}</span>
              <span><i class="cl">Function</i>{{ l.chemicals || '-' }}</span>
              <span class="lt__item"><i class="cl">Item</i>{{ l.item }}<small v-if="l.item_name && l.item_name !== l.item" class="lt__iname">{{ l.item_name }}</small></span>
              <span class="r"><i class="cl">Dosage</i>{{ l.dosage }}</span>
              <span><i class="cl">UOM</i>{{ l.uom }}</span>
              <span class="lt__total"><i class="cl">Total (kg)</i>{{ fmt(l.total, 3) }}</span>
              <span></span>
            </div>
          </div>
        </div>

        <!-- Chemicals summary -->
        <div class="card" v-if="ctx.summary.length">
          <div class="section-title">Chemicals for this Job Card</div>
          <div class="sum sum--h"><span>Chemical</span><span>Chart</span><span>Added</span><span>Issued</span></div>
          <div class="sum" v-for="s in ctx.summary" :key="s.item">
            <span class="sum__n">{{ s.item_name || s.item }}</span>
            <span>{{ fmt(s.planned, 3) }}</span><span>{{ fmt(s.added, 3) }}</span>
            <span :class="{ low: s.issued + 0.0005 < s.planned + s.added }">{{ fmt(s.issued, 3) }}</span>
          </div>
          <button class="btn btn-outline btn-full" style="margin-top:10px" @click="router.push({ path: BASE + '/chemical-issue', query: { jc: jobCard } })">🧪 Issue the chart's chemicals</button>
        </div>

        <!-- Additions -->
        <div class="card" v-if="ctx.dye_chart">
          <div class="section-title">Add chemical during dyeing</div>
          <template v-if="ctx.can_add">
            <label class="form-label">Chemical Store *</label>
            <AsyncSelect v-model="store" :fetcher="warehouseFetcher" @select="saveStore" />
            <label class="form-label" style="margin-top:10px">Chemical</label>
            <select v-model="addPick" class="form-input" @change="onPick">
              <option value="">— choose —</option>
              <option v-for="l in chartChemicals" :key="l.key" :value="l.key">{{ l.label }}</option>
              <option value="__other">Another chemical…</option>
            </select>
            <div v-if="addPick === '__other'" style="margin-top:8px">
              <AsyncSelect v-model="add.item" :fetcher="itemFetcher" placeholder="Search chemical item" />
            </div>
            <div class="grid-2" style="margin-top:10px">
              <div><label class="form-label">Bath</label><input v-model="add.bath_no" class="form-input" /></div>
              <div><label class="form-label">Function</label><input v-model="add.chemicals" class="form-input" list="dye-functions" /></div>
            </div>
            <label class="form-label" style="margin-top:10px">Quantity</label>
            <input v-model.number="add.qty" type="number" step="0.001" class="form-input" placeholder="qty in stock UOM" />
            <BatchAllocator v-if="add.item && add.qty > 0 && store" :key="add.item" :item-code="add.item" :warehouse="store"
                            :qty="Number(add.qty) || 0" @update:allocations="a => (add.allocations = a)" />
            <label class="form-label" style="margin-top:10px">Remarks</label>
            <input v-model="add.remarks" class="form-input" placeholder="e.g. shade correction" />
            <button class="btn btn-primary btn-full btn-lg" style="margin-top:12px" :disabled="adding || !store || !add.item || !(add.qty > 0)" @click="addChemical">
              {{ adding ? 'Issuing…' : 'Add & Issue' }}
            </button>
            <div class="hint">Issued at once from {{ store || 'the chemical store' }} to WIP (an MTM against this Job Card) and recorded on the Dye Chart.</div>
          </template>
          <div v-else class="alert alert-warning">
            <template v-if="ctx.job_card.docstatus !== 0">The Job Card is {{ ctx.job_card.status }} — no more additions.</template>
            <template v-else>
              Start the Job Card to add chemicals.
              <button class="btn btn-primary" style="margin-left:8px" :disabled="busy" @click="start">▶ Start Job Card</button>
            </template>
          </div>
          <div v-if="addMsg" class="alert" :class="addOk ? 'alert-success' : 'alert-error'" style="margin-top:10px">{{ addMsg }}</div>

          <div v-if="pendingAdds.length" class="adds">
            <div class="section-title" style="margin-top:14px">Waiting to sync ({{ pendingAdds.length }})</div>
            <div class="add add--pending" v-for="p in pendingAdds" :key="p.id">
              <div class="add__top"><b>{{ p.label }}</b>
                <span class="badge" :class="p._status === 'failed' ? 'badge-danger' : 'badge-warning'">{{ p._status === 'failed' ? 'refused' : 'on this device' }}</span></div>
              <div class="sub">{{ p.args.added_at }} · bath {{ p.args.bath_no || '-' }}<span v-if="p.args.chemicals"> · {{ p.args.chemicals }}</span>
                <span v-if="p.args.allocations?.length"> · {{ p.args.allocations.map(a => a.batch_no + ': ' + a.qty).join(', ') }}</span></div>
              <div v-if="p._error" class="sub" style="color:#b91c1c">{{ p._error }}</div>
            </div>
          </div>
          <div v-if="ctx.additions.length" class="adds">
            <div class="section-title" style="margin-top:14px">Additions ({{ ctx.additions.length }})</div>
            <div class="add" v-for="a in [...ctx.additions].reverse()" :key="a.name">
              <div class="add__top"><b>#{{ a.addition_no }} {{ a.item_name || a.item }}</b><span>{{ fmt(a.qty, 3) }} {{ a.stock_uom }}</span></div>
              <div class="sub">{{ a.posting_datetime }} · bath {{ a.bath_no || '-' }}<span v-if="a.chemicals"> · {{ a.chemicals }}</span> · {{ a.stock_entry }}</div>
              <div class="sub">Batches: {{ a.batches }}<span v-if="a.remarks"> · {{ a.remarks }}</span></div>
            </div>
          </div>
        </div>

        <!-- End -->
        <div class="card" v-if="ctx.job_card.docstatus === 0 && ctx.job_card.running">
          <div class="section-title">Dyeing done</div>
          <label class="form-label">Completed qty (kg)</label>
          <input v-model.number="completedQty" type="number" step="0.001" class="form-input" />
          <button class="btn btn-primary btn-full btn-lg" style="margin-top:10px" :disabled="busy" @click="endJob">
            {{ busy ? 'Ending…' : '■ End Job Card' }}
          </button>
          <div class="hint">Stops the timer and submits the Job Card. No more additions after this.</div>
        </div>
        <div v-if="actionError" class="alert alert-error">{{ actionError }}</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import BatchAllocator from '@/components/BatchAllocator.vue'
import { api } from '@/api/frappe'
import { db } from '@/db'
import { callOrQueue, localNow } from '@/composables/useSync'
import { cached, startJobCard, completeJobCard, applyJobCardOverlay, jcGroup } from '@/composables/useOffline'
import { BASE, fmt, statusClass, warehouseFetcher } from '@/utils'

const props = defineProps({ jobCard: String })
const router = useRouter()
const FUNCTIONS = ['Deoiling', 'Lubricant', 'Dyes 1', 'Dyes 2', 'Dyes 3', 'Levelling agent', 'Dispersing Agent',
  'Acid Buffer', 'Alkali', 'Reduction Clearing Agent', 'Acetic Acid', 'Wicking', 'Antimicrobial', 'Caustic Soda',
  'Hydros', 'Mild Alkali', 'Fixing agent', 'Wetting agent', 'Bleaching agent', 'Soaping agent', 'Peroxide killer']

const ctx = ref(null)
const loading = ref(false)
const error = ref('')
const recipe = ref('')
const lotWeight = ref(0)
const lines = ref([])
const saving = ref(false)
const saveMsg = ref('')
const saveOk = ref(false)
const busy = ref(false)
const actionError = ref('')
const completedQty = ref(0)

const addPick = ref('')
const add = reactive({ item: '', bath_no: '', chemicals: '', qty: null, remarks: '', allocations: [] })
const adding = ref(false)
// the Job Card's unit store (from settings); the user can change it here
const store = ref('')
function saveStore() { add.allocations = [] }
const offlineAt = ref(null)
const pendingMsg = ref('')
const pendingAdds = ref([])   // additions queued on this device, not yet in ERPNext
const addMsg = ref('')
const addOk = ref(false)

const editable = computed(() => ctx.value && ctx.value.job_card.docstatus === 0
  && (!ctx.value.dye_chart || ctx.value.dye_chart.docstatus === 0))
const chartChemicals = computed(() => (ctx.value?.lines || []).filter(l => l.item).map((l, i) => ({
  key: String(i), item: l.item, bath_no: l.bath_no, chemicals: l.chemicals,
  label: `B${l.bath_no || '-'} · ${l.item_name || l.item}${l.chemicals ? ' · ' + l.chemicals : ''}`,
})))

// MLR as "6" or "1:6" (liquor ratio) → 6
function mlrNum(v) {
  const t = String(v ?? '').trim()
  const m = t.match(/^\s*[\d.]+\s*:\s*([\d.]+)\s*$/)
  return m ? Number(m[1]) || 0 : Number(t) || 0
}
function lineTotal(l) {
  const lot = Number(lotWeight.value) || 0, d = Number(l.dosage) || 0, mlr = mlrNum(l.mlr)
  return l.uom === 'GPL' ? lot * d / 1000 * mlr : lot * d / 100
}

const recipeFetcher = async (txt) => (await api.searchRecipes(txt, ctx.value?.job_card.production_item)).map(r => ({
  value: r.name, description: [r.item, `${r.line_count} lines`, r.is_default ? 'default' : '', r.docstatus === 1 ? 'submitted' : 'draft'].filter(Boolean).join(' · '),
}))
const itemFetcher = async (txt) => (await api.searchLink('Item', txt, { disabled: 0 }, ['name', 'item_name'])).map(i => ({
  value: i.name, description: i.item_name,
}))

async function loadRecipe(name) {
  if (lines.value.some(l => l.item) && !confirm('Replace the current lines with this recipe?')) return
  lines.value = (await api.recipeLines(name)).map(r => ({ ...r }))
}

async function load() {
  loading.value = !ctx.value
  error.value = ''
  try {
    const r = await cached('dc:' + props.jobCard, () => api.dyeContext(props.jobCard))
    ctx.value = r.data
    offlineAt.value = r.offline ? r.at : null
    const jc = ctx.value.job_card
    const ovl = await applyJobCardOverlay(props.jobCard, jc)
    if (ovl) {
      if (jc.pending_end) jc.docstatus = 1
      ctx.value.can_add = !!(jc.running && jc.docstatus === 0 && ctx.value.dye_chart)
    }
    pendingMsg.value = !ovl ? '' : ovl.ended_at
      ? `Ended at ${ovl.ended_at} on this device — waiting to sync to ERPNext.`
      : `Started at ${ovl.running_since} on this device — waiting to sync to ERPNext.`
    pendingAdds.value = (await db.syncQueue.where('group').equals(jcGroup(props.jobCard)).toArray())
      .filter(x => x.method.endsWith('dye.add_chemical') && x._status !== 'synced')
    const dc = ctx.value.dye_chart
    recipe.value = dc?.dye_receipe || ctx.value.suggested_recipe || ''
    lotWeight.value = dc?.lot_weight || ctx.value.default_lot_weight
    // new chart: the item's default recipe is loaded automatically
    lines.value = (dc ? ctx.value.lines : ctx.value.suggested_lines || []).map(l => ({ ...l }))
    completedQty.value = ctx.value.job_card.for_quantity
    if (!store.value) store.value = ctx.value.chemical_store || ''
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function save(submit) {
  if (submit && !confirm('Submit the Dye Chart? Lines can\'t be changed after this; anything extra goes in as an addition.')) return
  saving.value = true
  saveMsg.value = ''
  try {
    const r = await api.saveDyeChart(props.jobCard, lotWeight.value, lines.value, recipe.value || undefined, submit ? 1 : 0)
    saveOk.value = true
    saveMsg.value = `Dye Chart ${r.dye_chart} ${r.docstatus === 1 ? 'submitted' : 'saved'} and the Job Card's chemicals updated.`
    await load()
  } catch (err) {
    saveOk.value = false
    saveMsg.value = err.message
  } finally {
    saving.value = false
  }
}

function onPick() {
  const l = chartChemicals.value.find(c => c.key === addPick.value)
  add.item = l ? l.item : ''
  add.bath_no = l ? (l.bath_no || '') : add.bath_no
  add.chemicals = l ? (l.chemicals || '') : ''
  add.allocations = []
}

async function addChemical() {
  adding.value = true
  addMsg.value = ''
  try {
    const itemName = chartChemicals.value.find(c => c.item === add.item)?.label || add.item
    const r = await callOrQueue('pranera_production.api.dye.add_chemical', {
      job_card: props.jobCard, item_code: add.item, qty: add.qty, allocations: add.allocations, source_warehouse: store.value,
      bath_no: add.bath_no || undefined, chemicals: add.chemicals || undefined, remarks: add.remarks || undefined,
      added_at: localNow(), offline: 1,
    }, `Add ${add.qty} ${itemName} · ${props.jobCard}`, { group: jcGroup(props.jobCard), clientId: true })
    addOk.value = true
    addMsg.value = r?.queued
      ? `${add.qty} of ${add.item} saved on this device — it will be issued when the connection is back.`
      : `Addition #${r.addition_no}: ${add.qty} of ${add.item} issued (${r.stock_entry}).`
    Object.assign(add, { item: '', bath_no: '', chemicals: '', qty: null, remarks: '', allocations: [] })
    addPick.value = ''
    await load()
  } catch (err) {
    addOk.value = false
    addMsg.value = err.message
  } finally {
    adding.value = false
  }
}

async function start() {
  busy.value = true
  actionError.value = ''
  try { await startJobCard(props.jobCard); await load() } catch (err) { actionError.value = err.message }
  busy.value = false
}

async function endJob() {
  if (!confirm(`End Job Card ${props.jobCard} with ${completedQty.value} kg completed?`)) return
  busy.value = true
  actionError.value = ''
  try { await completeJobCard(props.jobCard, completedQty.value); await load() } catch (err) { actionError.value = err.message }
  busy.value = false
}

const onSynced = (e) => { if (e.detail?.group === jcGroup(props.jobCard)) load() }
onMounted(() => { load(); window.addEventListener('prod:queue-synced', onSynced) })
onUnmounted(() => window.removeEventListener('prod:queue-synced', onSynced))
</script>

<style scoped>
.row-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 6px; }
.dc-wide { max-width: 1180px !important; }
.add--pending { background: #fffbeb; border-radius: 8px; padding: 8px; margin: 4px 0; }
.lt--ro .lt__row { font-size: 13px; padding: 8px 10px; }
.lt--ro .lt__item { overflow-wrap: anywhere; }
.lt__iname { display: block; font-size: 11px; color: var(--slate-500); }
.lt { margin: 14px 0 8px; border: 1px solid var(--slate-200); border-radius: 10px; overflow: hidden; }
.lt__row { display: grid; grid-template-columns: 36px 64px 64px minmax(120px, 1.1fr) minmax(200px, 2fr) 92px 122px 84px 32px;
  gap: 8px; align-items: center; padding: 6px 10px; border-bottom: 1px solid var(--slate-100); }
.lt__row:last-of-type { border-bottom: none; }
.lt__head { background: var(--slate-50); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--slate-500); padding: 9px 10px; }
.lt__row .form-input { padding: 7px 8px; font-size: 13px; min-width: 0; width: 100%; }
.lt__row label { min-width: 0; margin: 0; }
.lt__no { font-weight: 700; color: var(--slate-500); font-size: 13px; }
.lt__total { font-weight: 700; font-size: 13px; text-align: right; }
.r { text-align: right; }
.cl { display: none; }
@media (max-width: 860px) {
  .lt { border: none; }
  .lt__head { display: none; }
  .lt__row { grid-template-columns: 1fr 1fr 1fr; border: 1px solid var(--slate-200); border-radius: 10px; margin-bottom: 8px; padding: 10px; position: relative; }
  .lt__item, .lt__row label:nth-of-type(3) { grid-column: 1 / -1; }
  .lt__no { grid-column: 1 / -1; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
  .lt__no .cl { display: none; }
  .lt__no::before { content: 'Line '; }
  .lt__total { text-align: left; }
  .lt__row .x { position: absolute; top: 6px; right: 6px; }
  .cl { display: block; font-style: normal; font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--slate-500); margin-bottom: 3px; }
}
.x { border: none; background: none; color: var(--slate-400); font-size: 15px; padding: 4px 6px; cursor: pointer; }
.totals { font-size: 13px; margin: 8px 0 12px; }
.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; }
.ro { display: flex; gap: 10px; align-items: baseline; padding: 7px 0; border-bottom: 1px solid var(--slate-100); font-size: 13px; }
.ro__bath { font-weight: 700; color: var(--slate-500); min-width: 28px; }
.ro__name { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.ro__name small { display: block; color: var(--slate-500); font-size: 11.5px; }
.ro__qty { font-weight: 700; }
.sum { display: grid; grid-template-columns: 1fr 64px 64px 64px; gap: 6px; font-size: 12.5px; padding: 5px 0; border-bottom: 1px solid var(--slate-100); text-align: right; }
.sum span:first-child { text-align: left; }
.sum--h { font-size: 11px; text-transform: uppercase; color: var(--slate-500); font-weight: 700; }
.sum__n { overflow-wrap: anywhere; }
.low { color: var(--amber-600); font-weight: 700; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.add { padding: 8px 0; border-bottom: 1px solid var(--slate-100); }
.add__top { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; }
</style>
