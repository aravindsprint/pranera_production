<template>
  <div class="page">
    <AppHeader title="Roll Trace" subtitle="Live state & process history" active="rolls" />
    <div class="page-content">
      <div class="search">
        <input v-model="txt" class="form-input" placeholder="Roll no / batch / work order" @keyup.enter="search" />
        <button class="btn btn-primary" @click="scannerOpen = true">📷</button>
        <button class="btn btn-outline" @click="search">Go</button>
      </div>
      <div class="filters">
        <select v-model="status" class="form-input" @change="search">
          <option value="">Any status</option><option>In Process</option><option>In Stock</option>
        </select>
      </div>
      <div v-if="error" class="alert alert-error">{{ error }}</div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>

      <!-- Trace -->
      <template v-if="trace">
        <div class="card">
          <div class="t-top">
            <span class="t-no">{{ trace.roll.name }}</span>
            <span class="badge" :class="statusClass(trace.roll.current_status || 'In Stock')">{{ trace.roll.current_status || 'Greige / not processed' }}</span>
            <span v-if="trace.roll.current_grade" class="badge" :class="gradeClass(trace.roll.current_grade)">Grade {{ trace.roll.current_grade }}</span>
          </div>
          <div class="kv"><span>Current item</span><b>{{ trace.roll.current_item }}</b></div>
          <div class="kv"><span>Current batch</span><b>{{ trace.roll.current_batch }}</b></div>
          <div class="kv"><span>Weight now</span><b>{{ fmt(trace.roll.current_weight, 3) }} {{ isPcs(trace.roll.stock_uom) ? '(kg) · ' + trace.roll.total_qty + ' pcs' : 'kg' }}</b></div>
          <div class="kv"><span>Warehouse</span><b>{{ trace.roll.current_warehouse }}</b></div>
          <div class="kv" v-if="trace.roll.current_process"><span>Process</span><b>{{ trace.roll.current_process }} · {{ trace.roll.current_work_order }}</b></div>
          <div class="kv" v-if="trace.roll.current_process_loss"><span>Total process loss</span><b>{{ fmt(trace.roll.current_process_loss, 3) }} kg</b></div>
          <div class="divider"></div>
          <div class="kv"><span>Greige item</span><b>{{ trace.roll.item_code }}</b></div>
          <div class="kv"><span>Greige batch</span><b>{{ trace.roll.batch }}</b></div>
          <div class="kv"><span>Greige weight</span><b>{{ fmt(trace.roll.roll_weight, 3) }}</b></div>
          <div class="kv" v-if="trace.roll.knitting_work_order"><span>Knitting</span><b>{{ trace.roll.knitting_work_order }} · {{ trace.roll.knitting_machine_no }}</b></div>
          <div class="kv" v-if="trace.roll.purchase_order || trace.roll.subcontracting_order"><span>Inward</span><b>{{ trace.roll.purchase_order || trace.roll.subcontracting_order }}</b></div>
        </div>

        <div class="card">
          <div class="section-title">Process history</div>
          <div v-if="!trace.history.length" class="hint">Not processed yet.</div>
          <div class="tl" v-for="h in trace.history" :key="h.idx">
            <div class="tl__dot"></div>
            <div class="tl__body">
              <div class="tl__head"><b>{{ h.event }}</b> · {{ h.operation }} <span class="tl__date">{{ h.datetime || h.date }}</span></div>
              <div class="tl__meta">{{ h.document_type }} {{ h.document_name }}<span v-if="h.job_card"> · {{ h.job_card }}</span></div>
              <div class="tl__meta" v-if="h.source_item !== h.target_item">{{ h.source_item }} → {{ h.target_item }}</div>
              <div class="tl__meta" v-if="h.source_batch !== h.target_batch">{{ h.source_batch }} → {{ h.target_batch }}</div>
              <div class="tl__meta" v-if="h.source_warehouse !== h.target_warehouse">{{ h.source_warehouse }} → {{ h.target_warehouse }}</div>
              <div class="tl__meta">{{ fmt(h.weight_before, 3) }} → <b>{{ fmt(h.weight_after, 3) }}</b><span v-if="h.process_loss"> · loss {{ fmt(h.process_loss, 3) }}</span></div>
            </div>
          </div>
        </div>

        <div class="card" v-if="trace.inspections.length">
          <div class="section-title">Inspections</div>
          <div class="insp" v-for="i in trace.inspections" :key="i.name">
            <div class="insp__top"><b>{{ i.name }}</b><span class="badge" :class="gradeClass(i.grade)">G{{ i.grade }}</span></div>
            <div class="tl__meta">{{ i.inspected_on }} · {{ i.checker_name }} · {{ i.job_card }}</div>
            <div class="tl__meta">{{ fmt(i.roll_weight, 3) }} kg · width {{ i.width }} · GSM {{ i.gsm }} · {{ i.total_points }} pts · {{ fmt(i.point_percentage) }}%</div>
            <div class="tl__meta" v-if="i.mistakes.length">{{ i.mistakes.map(m => `${m.mistake} (${m.total_points})`).join(', ') }}</div>
          </div>
        </div>

        <div class="card" v-if="trace.packing_lists.length">
          <div class="section-title">Packing lists</div>
          <div class="iss" v-for="p in trace.packing_lists" :key="p.name"><span>{{ p.name }}</span><span>{{ p.stock_entry }}</span><span>{{ fmt(p.roll_weight, 3) }}</span></div>
        </div>
        <div class="card" v-if="trace.cut_rolls.length">
          <div class="section-title">Cut into</div>
          <div class="iss" v-for="c in trace.cut_rolls" :key="c.name" @click="open(c.name)"><span>{{ c.name }}</span><span>{{ fmt(c.current_weight || c.roll_weight, 3) }}</span></div>
        </div>
        <button class="btn btn-ghost btn-full" @click="trace = null">Back to results</button>
      </template>

      <!-- Results -->
      <template v-else>
        <button v-for="r in results" :key="r.name" class="card res" @click="open(r.name)">
          <div class="res__top"><b>{{ r.name }}</b><span class="badge" :class="statusClass(r.current_status || 'In Stock')">{{ r.current_status || 'Greige' }}</span></div>
          <div class="tl__meta">{{ r.current_item || r.item_code }}</div>
          <div class="tl__meta">{{ r.current_batch || r.batch }} · {{ fmt(r.current_weight || r.roll_weight, 3) }}<span v-if="r.current_process"> · {{ r.current_process }}</span></div>
        </button>
      </template>
      <ScannerModal v-model="scannerOpen" title="Scan roll" :allow-manual="true" @scanned="t => { txt = t; open(t) }" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import ScannerModal from '@/components/ScannerModal.vue'
import { api } from '@/api/frappe'
import { fmt, statusClass, gradeClass, isPcs } from '@/utils'

const route = useRoute()
const txt = ref('')
const status = ref('')
const results = ref([])
const trace = ref(null)
const loading = ref(false)
const error = ref('')
const scannerOpen = ref(false)

async function search() {
  trace.value = null
  loading.value = true
  error.value = ''
  try {
    results.value = await api.searchRolls({ txt: txt.value || undefined, status: status.value || undefined })
    if (results.value.length === 1 && txt.value) await open(results.value[0].name)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
async function open(rollNo) {
  loading.value = true
  error.value = ''
  try { trace.value = await api.rollTrace(rollNo) } catch (err) { error.value = err.message }
  loading.value = false
}
onMounted(() => { if (route.query.roll) open(String(route.query.roll)); else search() })
</script>

<style scoped>
.search { display: flex; gap: 8px; margin-bottom: 8px; }
.search .form-input { flex: 1; }
.filters { margin-bottom: 12px; }
.t-top { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
.t-no { font-size: 20px; font-weight: 800; }
.kv { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; padding: 4px 0; }
.kv span { color: var(--slate-500); white-space: nowrap; }
.kv b { text-align: right; overflow-wrap: anywhere; }
.tl { display: flex; gap: 10px; padding: 8px 0; border-left: 2px solid var(--slate-200); margin-left: 6px; padding-left: 12px; position: relative; }
.tl__dot { position: absolute; left: -7px; top: 12px; width: 12px; height: 12px; border-radius: 50%; background: var(--app-primary); }
.tl__head { font-size: 13px; }
.tl__date { color: var(--slate-400); font-size: 11px; }
.tl__meta { font-size: 12px; color: var(--slate-500); overflow-wrap: anywhere; margin-top: 2px; }
.insp { padding: 8px 0; border-bottom: 1px solid var(--slate-100); }
.insp__top { display: flex; justify-content: space-between; }
.iss { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; padding: 6px 0; border-bottom: 1px solid var(--slate-100); }
.res { display: block; width: 100%; text-align: left; }
.res__top { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: 12px; color: var(--slate-500); }
</style>
