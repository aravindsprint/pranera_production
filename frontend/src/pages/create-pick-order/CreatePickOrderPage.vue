<template>
  <div class="page">
    <AppHeader title="Create Pick Order" subtitle="Lot section → Job Card (MTM)" active="create-pick-order" :show-back="true" />
    <div class="page-content">

      <div class="card">
        <label class="form-label">Work Order *</label>
        <AsyncSelect v-model="workOrder" :fetcher="woFetcher" placeholder="Search work order / item / project" @select="onWorkOrder" />
      </div>

      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <template v-if="ctx">
        <div class="card">
          <div class="wo-title">{{ ctx.work_order.production_item }}</div>
          <div class="wo-sub">{{ ctx.work_order.item_name }}</div>
          <div class="wo-meta">
            <span>Qty {{ fmt(ctx.work_order.qty) }} {{ ctx.work_order.stock_uom }}</span>
            <span v-if="ctx.work_order.color">{{ ctx.work_order.color }}</span>
            <span v-if="ctx.work_order.project">{{ ctx.work_order.project }}</span>
          </div>
          <div class="wo-meta" v-if="ctx.in_process?.rolls">
            <span class="badge badge-info">{{ ctx.in_process.rolls }} rolls already in process ({{ fmt(ctx.in_process.weight) }} kg)</span>
          </div>

          <div class="section-title" style="margin-top:14px">Operations</div>
          <div class="ops">
            <button v-for="op in ctx.operations" :key="op.name" class="op"
                    :class="{ 'op--sel': jobCard === op.job_card, 'op--dis': !op.job_card }"
                    :disabled="!op.job_card" @click="jobCard = op.job_card">
              <div class="op__name">{{ op.sequence_id || op.idx }}. {{ op.operation }}</div>
              <div class="op__jc">{{ op.job_card || 'No job card yet' }}</div>
            </button>
          </div>
          <div class="hint">Material goes to the Job Card you select (normally the first operation). Target: <b>{{ ctx.work_order.wip_warehouse }}</b></div>
        </div>

        <div class="card">
          <div class="section-title">Required items</div>
          <div class="req" v-for="r in ctx.required_items" :key="r.item_code">
            <div class="req__item">{{ r.item_code }}</div>
            <div class="req__qty">{{ fmt(r.transferred_qty) }} / {{ fmt(r.required_qty) }} {{ r.stock_uom }}</div>
          </div>
        </div>

        <div class="card">
          <div class="section-title">Lot batches available (not in process)</div>
          <div v-if="!ctx.available_batches.length" class="hint">No rolls of the required items found.</div>
          <template v-else>
            <input v-model="batchSearch" type="search" class="form-input batch-search" placeholder="Search batch, item or warehouse" />
            <div class="hint batch-count">
              {{ filteredBatches.length }} of {{ ctx.available_batches.length }} batches
              <span v-if="batchRows.length"> · {{ batchRows.length }} ticked</span>
            </div>
            <div v-if="!filteredBatches.length" class="hint">No batch matches “{{ batchSearch }}”.</div>
          </template>
          <div class="batch" v-for="b in filteredBatches" :key="b.batch + b.warehouse">
            <label class="batch__chk">
              <input type="checkbox" :checked="!!selected[b.batch]" @change="toggleBatch(b, $event.target.checked)" />
              <div>
                <div class="batch__name">{{ b.batch }}</div>
                <div class="batch__meta">{{ b.item_code }} · {{ b.warehouse }}</div>
                <div class="batch__meta">{{ b.rolls }} rolls · {{ fmt(b.weight) }} kg<span v-if="b.pcs"> · {{ b.pcs }} pcs</span></div>
              </div>
            </label>
            <input v-if="selected[b.batch]" v-model.number="selected[b.batch].qty" type="number" step="0.001" class="form-input batch__qty" />
          </div>
          <div class="hint">Tick batches to restrict the pick to them (qty per batch is the target). Leave all unticked for a free pick by total weight.</div>
        </div>

        <div class="card">
          <div class="form-group" v-if="!batchRows.length">
            <label class="form-label">Pick Qty (target, {{ ctx.work_order.stock_uom }}) *</label>
            <input v-model.number="pickQty" type="number" step="0.001" class="form-input" />
          </div>
          <div class="form-group" v-else>
            <label class="form-label">Pick Qty</label>
            <div class="big">{{ fmt(batchTotal) }}</div>
          </div>
          <div class="form-group">
            <label class="form-label">Source Warehouse (lot section) *</label>
            <AsyncSelect v-model="sourceWarehouse" :fetcher="warehouseFetcher" placeholder="Search warehouse" />
          </div>
          <div class="form-group">
            <label class="form-label">Assign To *</label>
            <AsyncSelect v-model="assignedTo" :fetcher="userFetcher" placeholder="Search user" />
          </div>
          <div class="form-group">
            <label class="form-label">Remarks</label>
            <textarea v-model="remarks" class="form-input" rows="2"></textarea>
          </div>
          <button class="btn btn-primary btn-full btn-lg" :disabled="!canSubmit || saving" @click="submit">
            {{ saving ? 'Creating…' : 'Create Pick Order' }}
          </button>
          <div v-if="done" class="alert alert-success" style="margin-top:12px">Created {{ done }}</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import { api } from '@/api/frappe'
import { fmt, warehouseFetcher, userFetcher } from '@/utils'

const workOrder = ref('')
const ctx = ref(null)
const loading = ref(false)
const error = ref('')
const jobCard = ref('')
const pickQty = ref(null)
const sourceWarehouse = ref('')
const assignedTo = ref('')
const remarks = ref('')
const selected = reactive({})
const saving = ref(false)
const done = ref('')

const woFetcher = async (txt) => (await api.searchWorkOrders(txt)).map(w => ({
  value: w.name, label: w.name, description: [w.production_item, w.color, w.project, w.status].filter(Boolean).join(' · '),
}))

async function onWorkOrder(o) {
  ctx.value = null
  error.value = ''
  done.value = ''
  Object.keys(selected).forEach(k => delete selected[k])
  batchSearch.value = ''
  if (!o) return
  loading.value = true
  try {
    ctx.value = await api.pickContext(o.value)
    jobCard.value = ctx.value.default_job_card || ''
    sourceWarehouse.value = ctx.value.work_order.source_warehouse || ''
    const remaining = (ctx.value.work_order.qty || 0) - (ctx.value.work_order.material_transferred_for_manufacturing || 0)
    pickQty.value = remaining > 0 ? Number(remaining.toFixed(3)) : null
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function toggleBatch(b, on) {
  if (on) {
    selected[b.batch] = { batch: b.batch, qty: Number(Number(b.weight || 0).toFixed(3)) }
    if (!sourceWarehouse.value) sourceWarehouse.value = b.warehouse
  } else delete selected[b.batch]
}

const batchRows = computed(() => Object.values(selected))
const batchSearch = ref('')
// Every word must match the batch, item or warehouse. Ticked batches always stay
// visible so a selection can't be hidden by the filter.
const filteredBatches = computed(() => {
  const all = ctx.value?.available_batches || []
  const words = batchSearch.value.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return all
  return all.filter(b => {
    if (selected[b.batch]) return true
    const hay = `${b.batch || ''} ${b.item_code || ''} ${b.warehouse || ''}`.toLowerCase()
    return words.every(w => hay.includes(w))
  })
})
const batchTotal = computed(() => batchRows.value.reduce((s, r) => s + (Number(r.qty) || 0), 0))
const canSubmit = computed(() => ctx.value && jobCard.value && sourceWarehouse.value && assignedTo.value &&
  (batchRows.value.length ? batchTotal.value > 0 : Number(pickQty.value) > 0))

async function submit() {
  saving.value = true
  error.value = ''
  try {
    const r = await api.createPickOrder({
      work_order: ctx.value.work_order.name,
      job_card: jobCard.value,
      assigned_to: assignedTo.value,
      source_warehouse: sourceWarehouse.value,
      pick_qty: batchRows.value.length ? undefined : pickQty.value,
      batch_items: batchRows.value.length ? batchRows.value : undefined,
      remarks: remarks.value || undefined,
    })
    done.value = r.name
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.wo-title { font-weight: 800; font-size: 15px; overflow-wrap: anywhere; }
.wo-sub { font-size: 12px; color: var(--slate-500); margin-top: 2px; }
.wo-meta { display: flex; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--slate-700); margin-top: 8px; }
.ops { display: flex; flex-direction: column; gap: 8px; }
.op { text-align: left; border: 1.5px solid var(--slate-200); background: #fff; border-radius: 10px; padding: 10px 12px; }
.op--sel { border-color: var(--app-primary); background: rgba(30,58,95,0.06); }
.op--dis { opacity: 0.5; }
.op__name { font-weight: 700; font-size: 14px; }
.op__jc { font-size: 12px; color: var(--slate-500); }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
.req { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--slate-100); font-size: 13px; }
.req__item { overflow-wrap: anywhere; }
.req__qty { white-space: nowrap; font-weight: 600; }
.batch-search { margin: 4px 0 6px; }
.batch-count { margin: 0 0 4px; }
.batch { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--slate-100); }
.batch__chk { display: flex; gap: 10px; flex: 1; min-width: 0; align-items: flex-start; }
.batch__chk input { margin-top: 4px; width: 18px; height: 18px; }
.batch__name { font-weight: 700; font-size: 13px; overflow-wrap: anywhere; }
.batch__meta { font-size: 12px; color: var(--slate-500); overflow-wrap: anywhere; }
.batch__qty { width: 110px; flex-shrink: 0; }
.big { font-size: 22px; font-weight: 800; }
</style>
