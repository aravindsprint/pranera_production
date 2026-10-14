<template>
  <div class="page">
    <AppHeader title="Dashboard" subtitle="Inspection & process production" active="dashboard" />
    <div class="page-content">
      <div class="range">
        <input v-model="from" type="date" class="form-input" />
        <input v-model="to" type="date" class="form-input" />
        <button class="btn btn-primary" @click="load">Go</button>
      </div>
      <div class="quick">
        <button class="btn btn-ghost" @click="setRange(0)">Today</button>
        <button class="btn btn-ghost" @click="setRange(6)">7 days</button>
        <button class="btn btn-ghost" @click="setRange(29)">30 days</button>
      </div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <template v-if="d">
        <div class="kpis">
          <div class="kpi"><span>Rolls inspected</span><b>{{ d.inspection.totals.rolls }}</b></div>
          <div class="kpi"><span>Weight inspected</span><b>{{ fmt(d.inspection.totals.weight, 0) }} kg</b></div>
          <div class="kpi"><span>Pcs inspected</span><b>{{ d.inspection.totals.pcs }}</b></div>
          <div class="kpi"><span>Avg points %</span><b>{{ fmt(d.inspection.totals.avg_pct) }}</b></div>
        </div>

        <div class="card">
          <div class="section-title">Grade-wise (weight)</div>
          <Bars :rows="d.inspection.by_grade" value="weight" :label="r => 'Grade ' + r.label" :extra="r => r.rolls + ' rolls'" />
        </div>
        <div class="card">
          <div class="section-title">Inspected per day (weight)</div>
          <Bars :rows="d.inspection.by_day" value="weight" :extra="r => r.rolls + ' rolls'" />
        </div>
        <div class="card">
          <div class="section-title">Checker-wise (weight)</div>
          <Bars :rows="d.inspection.by_checker" value="weight" :extra="r => r.rolls + ' rolls · ' + fmt(r.avg_pct) + '%'" />
        </div>
        <div class="card">
          <div class="section-title">Top mistakes (points)</div>
          <Bars :rows="d.inspection.by_mistake" value="points" :extra="r => r.rolls + ' rolls'" unit="pts" />
        </div>
        <div class="card">
          <div class="section-title">Production MF by operation (weight out)</div>
          <Bars :rows="d.production.by_operation" value="weight_out" :extra="r => r.rolls + ' rolls · loss ' + fmt(r.loss) + ' kg (' + fmt(r.weight_in ? r.loss / r.weight_in * 100 : 0) + '%)'" />
        </div>
        <div class="card">
          <div class="section-title">Rolls in process now</div>
          <Bars :rows="d.production.in_process" value="weight" :extra="r => r.rolls + ' rolls'" />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { api } from '@/api/frappe'
import { fmt, today, daysAgo } from '@/utils'

const from = ref(daysAgo(6))
const to = ref(today())
const d = ref(null)
const loading = ref(false)
const error = ref('')

// Small horizontal-bar list (no chart library needed on the floor tablets)
const Bars = (props) => {
  const rows = props.rows || []
  const max = Math.max(1, ...rows.map(r => Number(r[props.value]) || 0))
  if (!rows.length) return h('div', { class: 'hint' }, 'No data')
  return h('div', { class: 'bars' }, rows.map(r => {
    const v = Number(r[props.value]) || 0
    return h('div', { class: 'bar' }, [
      h('div', { class: 'bar__top' }, [
        h('span', { class: 'bar__label' }, props.label ? props.label(r) : String(r.label ?? '-')),
        h('span', { class: 'bar__val' }, fmt(v, 0) + ' ' + (props.unit || 'kg')),
      ]),
      h('div', { class: 'bar__track' }, [h('div', { class: 'bar__fill', style: { width: (v / max * 100) + '%' } })]),
      props.extra ? h('div', { class: 'bar__extra' }, props.extra(r)) : null,
    ])
  }))
}
Bars.props = ['rows', 'value', 'label', 'extra', 'unit']

function setRange(n) { from.value = daysAgo(n); to.value = today(); load() }

async function load() {
  loading.value = true
  error.value = ''
  try { d.value = await api.dashboard(from.value, to.value) } catch (err) { error.value = err.message }
  loading.value = false
}
onMounted(load)
</script>

<style scoped>
.range { display: flex; gap: 8px; margin-bottom: 8px; }
.range .form-input { flex: 1; min-width: 0; }
.quick { display: flex; gap: 8px; margin-bottom: 12px; }
.quick .btn { flex: 1; padding: 8px; }
.kpis { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.kpi { background: #fff; border: 1px solid var(--slate-200); border-radius: 14px; padding: 12px; display: flex; flex-direction: column; }
.kpi span { font-size: 11px; color: var(--slate-500); text-transform: uppercase; letter-spacing: 0.04em; }
.kpi b { font-size: 20px; margin-top: 4px; }
:deep(.bars) { display: flex; flex-direction: column; gap: 10px; }
:deep(.bar__top) { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; }
:deep(.bar__label) { font-weight: 600; overflow-wrap: anywhere; }
:deep(.bar__val) { font-weight: 700; white-space: nowrap; }
:deep(.bar__track) { height: 8px; background: var(--slate-100); border-radius: 8px; overflow: hidden; margin-top: 4px; }
:deep(.bar__fill) { height: 100%; background: var(--app-primary); border-radius: 8px; }
:deep(.bar__extra) { font-size: 11px; color: var(--slate-500); margin-top: 2px; }
:deep(.hint) { font-size: 12px; color: var(--slate-500); }
</style>
