<template>
  <div class="page">
    <AppHeader title="Chemical Issue" subtitle="Dyes & chemicals → Job Card (MTM)" active="chemical-issue" :show-back="!!ctx" />
    <div class="page-content">

      <!-- Job card queue -->
      <template v-if="!ctx">
        <input v-model="txt" class="form-input" placeholder="Search job card / work order / item" @input="debouncedList" style="margin-bottom:12px" />
        <div v-if="listLoading" class="loading-center"><div class="spinner"></div></div>
        <div v-else-if="!jobCards.length" class="empty-state"><div class="empty-state__icon">🧪</div><div class="empty-state__title">No open job cards with a Dye Chart</div></div>
        <button v-for="j in jobCards" :key="j.name" class="card jc" @click="openJc(j.name)">
          <div class="jc__top"><b>{{ j.name }}</b><span class="badge" :class="statusClass(j.status)">{{ j.status }}</span></div>
          <div class="jc__meta">{{ j.operation }} · {{ j.workstation }}</div>
          <div class="jc__meta">{{ j.work_order }} · {{ j.production_item }}</div>
          <div class="jc__meta">Dye Chart {{ j.dye_chart }} · {{ fmt(j.for_quantity) }} kg</div>
        </button>
      </template>

      <!-- Issue screen -->
      <template v-else>
        <div class="card">
          <div class="h">{{ ctx.job_card.name }} · {{ ctx.job_card.operation }}</div>
          <div class="sub">{{ ctx.work_order }} · {{ ctx.job_card.production_item }}</div>
          <div class="sub">Dye Chart <b>{{ ctx.dye_chart || '—' }}</b><span v-if="ctx.lot_weight"> · lot {{ fmt(ctx.lot_weight) }} kg</span></div>
          <div class="sub">To {{ ctx.wip_warehouse }}</div>
        </div>
        <div v-if="!ctx.dye_chart" class="alert alert-warning">No Dye Chart is linked to this Job Card.</div>

        <div class="card">
          <label class="form-label">Chemical Store *</label>
          <AsyncSelect v-model="store" :fetcher="warehouseFetcher" @select="reload" />
        </div>

        <div class="card" v-if="ctx.items.length">
          <div class="section-title">From Dye Chart</div>
          <div class="item" v-for="it in ctx.items" :key="it.item_code">
            <div class="item__head">
              <div class="item__code">{{ it.item_name || it.item_code }}</div>
              <div class="item__sub">{{ it.item_code }}</div>
            </div>
            <div class="item__nums">
              <span>Need <b>{{ fmt(it.required_qty, 3) }}</b></span>
              <span>Issued <b>{{ fmt(it.issued_qty, 3) }}</b></span>
              <span>Pending <b>{{ fmt(it.pending_qty, 3) }}</b></span>
              <span :class="{ short: it.available_qty < it.pending_qty }">Stock <b>{{ fmt(it.available_qty, 3) }}</b></span>
            </div>
            <div class="item__batches" v-if="it.batches.length">FIFO: {{ it.batches.map(b => `${b.batch_no || 'no batch'} (${fmt(b.qty, 3)})`).join(', ') }}</div>
            <div class="item__in">
              <input v-model.number="qty[it.item_code]" type="number" step="0.001" min="0" class="form-input" :placeholder="'0.000 ' + (it.stock_uom || '')" />
              <button class="btn btn-ghost" @click="qty[it.item_code] = it.pending_qty">Pending</button>
            </div>
          </div>
          <label class="form-label" style="margin-top:12px">Posting Date</label>
          <input v-model="postingDate" type="date" class="form-input" />
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="!hasQty || saving" @click="issue(false)">Save Draft</button>
            <button class="btn btn-primary" :disabled="!hasQty || saving" @click="issue(true)">{{ saving ? 'Issuing…' : 'Issue (Submit MTM)' }}</button>
          </div>
          <div v-if="error" class="alert alert-error" style="margin-top:10px">{{ error }}</div>
          <div v-if="done" class="alert alert-success" style="margin-top:10px">{{ done }}</div>
        </div>

        <div class="card" v-if="ctx.issues.length">
          <div class="section-title">Issues for this Job Card</div>
          <div class="iss" v-for="s in ctx.issues" :key="s.name">
            <span>{{ s.name }}</span><span>{{ s.posting_date }}</span>
            <span class="badge" :class="s.docstatus === 1 ? 'badge-success' : 'badge-warning'">{{ s.docstatus === 1 ? 'Submitted' : 'Draft' }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import AsyncSelect from '@/components/AsyncSelect.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/frappe'
import { fmt, today, statusClass, warehouseFetcher } from '@/utils'

const auth = useAuthStore()
const txt = ref('')
const jobCards = ref([])
const listLoading = ref(false)
const ctx = ref(null)
const store = ref(localStorage.getItem('PROD_CHEM_STORE') || '')
const qty = reactive({})
const postingDate = ref(today())
const saving = ref(false)
const error = ref('')
const done = ref('')
let t = null

async function list() {
  listLoading.value = true
  try { jobCards.value = await api.chemicalJobCards(txt.value) } catch (err) { error.value = err.message }
  listLoading.value = false
}
function debouncedList() { clearTimeout(t); t = setTimeout(list, 300) }

async function openJc(name) {
  error.value = ''
  done.value = ''
  if (!store.value) store.value = auth.settings.chemical_store_warehouse || ''
  ctx.value = await api.chemicalContext(name, store.value || undefined)
  if (!store.value) store.value = ctx.value.source_warehouse || ''
  Object.keys(qty).forEach(k => delete qty[k])
}
async function reload() {
  if (!ctx.value) return
  localStorage.setItem('PROD_CHEM_STORE', store.value || '')
  ctx.value = await api.chemicalContext(ctx.value.job_card.name, store.value || undefined)
}

const hasQty = computed(() => store.value && Object.values(qty).some(v => Number(v) > 0))

async function issue(final) {
  saving.value = true
  error.value = ''
  done.value = ''
  try {
    const items = Object.entries(qty).filter(([, v]) => Number(v) > 0).map(([item_code, v]) => ({ item_code, qty: v }))
    const r = await api.issueChemicals(ctx.value.job_card.name, store.value, items, postingDate.value, final ? 1 : 0)
    done.value = `${r.stock_entry} ${r.submitted ? 'submitted' : 'saved as draft'}`
    Object.keys(qty).forEach(k => delete qty[k])
    await reload()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

onMounted(list)
</script>

<style scoped>
.jc { display: block; width: 100%; text-align: left; }
.jc__top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.jc__meta { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.h { font-weight: 800; }
.sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.item { padding: 12px 0; border-bottom: 1px solid var(--slate-100); }
.item__code { font-weight: 700; font-size: 14px; overflow-wrap: anywhere; }
.item__sub { font-size: 11px; color: var(--slate-400); overflow-wrap: anywhere; }
.item__nums { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--slate-700); margin: 6px 0; }
.item__nums .short { color: var(--red-600); }
.item__batches { font-size: 11px; color: var(--slate-500); margin-bottom: 6px; overflow-wrap: anywhere; }
.item__in { display: flex; gap: 8px; }
.item__in .form-input { flex: 1; }
.btn-row { display: flex; gap: 10px; margin-top: 12px; }
.btn-row .btn { flex: 1; }
.iss { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; padding: 6px 0; border-bottom: 1px solid var(--slate-100); }
</style>
