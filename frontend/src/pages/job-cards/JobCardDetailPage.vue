<template>
  <div class="page">
    <AppHeader :title="d?.job_card.operation || 'Job Card'" :subtitle="jobCard" active="job-cards" :show-back="true" />
    <div class="page-content">
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <template v-if="d">
        <div class="card">
          <div class="row-top">
            <b>{{ d.job_card.workstation }}</b>
            <span class="badge" :class="statusClass(d.job_card.status)">{{ d.job_card.status }}</span>
          </div>
          <div class="sub">{{ d.work_order.name }} · {{ d.work_order.production_item }}</div>
          <div class="sub">{{ d.work_order.item_name }}</div>
          <div class="nums">
            <span>For <b>{{ fmt(d.job_card.for_quantity) }}</b></span>
            <span>Transferred <b>{{ fmt(d.job_card.transferred_qty) }}</b></span>
            <span>Completed <b>{{ fmt(d.job_card.total_completed_qty) }}</b></span>
          </div>
          <div v-if="d.job_card.running_since" class="alert alert-info" style="margin-top:10px">Running since {{ d.job_card.running_since }}</div>
        </div>

        <div class="card">
          <div class="section-title">Operations</div>
          <div class="ops">
            <div v-for="op in d.operations" :key="op.name" class="op" :class="{ 'op--cur': op.is_current }">
              <span class="op__n">{{ op.sequence_id || op.idx }}</span>
              <span class="op__name">{{ op.operation }}</span>
              <span class="badge" :class="statusClass(op.jc_status)">{{ op.jc_status || '—' }}</span>
            </div>
          </div>
        </div>

        <div class="card" v-if="d.job_card.docstatus === 0">
          <div class="btn-row">
            <button class="btn btn-outline" :disabled="busy || !!d.job_card.running_since" @click="start">▶ Start</button>
            <button class="btn btn-primary" :disabled="busy" @click="showComplete = true">✔ Complete</button>
          </div>
          <div class="hint" v-if="!d.job_card.is_last_operation">Completing moves the rolls on to the next operation.</div>
          <div class="hint" v-else>Last operation — after completing, go to Manufacture (MF).</div>
          <div v-if="actionError" class="alert alert-error" style="margin-top:10px">{{ actionError }}</div>
        </div>
        <button v-if="d.job_card.is_inspection" class="btn btn-primary btn-full btn-lg" style="margin-bottom:12px"
                @click="router.push(BASE + '/inspection/' + encodeURIComponent(jobCard))">🔍 Open Inspection</button>
        <button v-if="d.job_card.is_last_operation && d.rolls.length" class="btn btn-outline btn-full" style="margin-bottom:12px"
                @click="router.push({ path: BASE + '/manufacture', query: { wo: d.work_order.name } })">🏭 Manufacture (MF)</button>

        <div class="card">
          <div class="section-title">Rolls at this Job Card ({{ d.rolls.length }} · {{ fmt(rollWeight) }} kg)</div>
          <div v-if="!d.rolls.length" class="hint">No rolls issued to this Job Card yet.</div>
          <div class="roll" v-for="r in d.rolls" :key="r.name">
            <span class="roll__no">{{ r.name }}</span>
            <span class="roll__b">{{ r.current_batch }}</span>
            <span class="roll__w">{{ fmt(r.current_weight) }}</span>
            <span v-if="r.current_grade" class="badge" :class="gradeClass(r.current_grade)">G{{ r.current_grade }}</span>
          </div>
        </div>

        <div class="card" v-if="d.issues.length">
          <div class="section-title">Material issued (MTM)</div>
          <div class="iss" v-for="(s, i) in d.issues" :key="i">
            <span class="iss__se">{{ s.name }}</span>
            <span class="iss__it">{{ s.item_code }}</span>
            <span class="iss__q">{{ fmt(s.qty, 3) }} {{ s.uom }}</span>
          </div>
        </div>

        <div class="card" v-if="d.manufactures.length">
          <div class="section-title">Manufacture entries (Work Order)</div>
          <div class="iss" v-for="m in d.manufactures" :key="m.name">
            <span class="iss__se">{{ m.name }}</span><span>{{ m.posting_date }}</span><span class="iss__q">{{ fmt(m.fg_completed_qty) }}</span>
          </div>
        </div>
      </template>

      <div v-if="showComplete" class="ov" @click.self="showComplete = false">
        <div class="ov__box">
          <div class="section-title">Complete {{ d.job_card.operation }}</div>
          <label class="form-label">Completed Qty</label>
          <input v-model.number="completedQty" type="number" step="0.001" class="form-input" />
          <div class="hint">Defaults to the Job Card quantity.</div>
          <div class="btn-row">
            <button class="btn btn-ghost" @click="showComplete = false">Cancel</button>
            <button class="btn btn-primary" :disabled="busy" @click="complete">{{ busy ? 'Saving…' : 'Complete & Submit' }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { api } from '@/api/frappe'
import { BASE, fmt, statusClass, gradeClass } from '@/utils'

const props = defineProps({ jobCard: String })
const router = useRouter()
const d = ref(null)
const loading = ref(false)
const error = ref('')
const busy = ref(false)
const actionError = ref('')
const showComplete = ref(false)
const completedQty = ref(null)

const rollWeight = computed(() => (d.value?.rolls || []).reduce((s, r) => s + (Number(r.current_weight) || 0), 0))

async function load() {
  loading.value = true
  error.value = ''
  try {
    d.value = await api.jobCardDetail(props.jobCard)
    const done = (d.value.job_card.total_completed_qty || 0)
    completedQty.value = Number(Math.max(0, (d.value.job_card.for_quantity || 0) - done).toFixed(3))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
async function start() {
  busy.value = true
  actionError.value = ''
  try { await api.startJobCard(props.jobCard); await load() } catch (err) { actionError.value = err.message }
  busy.value = false
}
async function complete() {
  busy.value = true
  actionError.value = ''
  try {
    await api.completeJobCard(props.jobCard, completedQty.value, 1)
    showComplete.value = false
    await load()
  } catch (err) {
    actionError.value = err.message
    showComplete.value = false
  }
  busy.value = false
}
onMounted(load)
</script>

<style scoped>
.row-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.sub { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.nums { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; margin-top: 8px; }
.ops { display: flex; flex-direction: column; gap: 6px; }
.op { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--slate-200); }
.op--cur { border-color: var(--app-primary); background: rgba(30,58,95,0.06); }
.op__n { width: 22px; height: 22px; border-radius: 50%; background: var(--slate-100); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.op__name { flex: 1; font-weight: 600; font-size: 14px; }
.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
.roll { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--slate-100); font-size: 13px; }
.roll__no { font-weight: 700; min-width: 70px; }
.roll__b { flex: 1; color: var(--slate-500); font-size: 11px; overflow-wrap: anywhere; }
.roll__w { font-weight: 700; }
.iss { display: flex; gap: 8px; font-size: 12px; padding: 6px 0; border-bottom: 1px solid var(--slate-100); }
.iss__se { font-weight: 600; white-space: nowrap; }
.iss__it { flex: 1; color: var(--slate-500); overflow-wrap: anywhere; }
.iss__q { font-weight: 700; white-space: nowrap; margin-left: auto; }
.ov { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center; justify-content: center; z-index: 500; padding: 20px; }
.ov__box { background: #fff; border-radius: 14px; padding: 20px; width: 100%; max-width: 380px; }
.ov__box .btn-row { margin-top: 14px; }
</style>
