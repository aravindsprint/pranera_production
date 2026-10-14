<template>
  <div class="page">
    <AppHeader title="Pivot" subtitle="Slice inspection / production data" active="pivot" />
    <div class="page-content wide">
      <div class="card controls">
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">Data</label>
            <select v-model="dataset" class="form-input" @change="load">
              <option value="inspection">Roll inspections</option>
              <option value="production">Production MF (per roll)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Measure</label>
            <select v-model="measure" class="form-input">
              <option value="__count">Count of rolls</option>
              <option v-for="m in numericCols" :key="m" :value="m">Sum of {{ m }}</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Rows</label>
            <select v-model="rowDim" class="form-input"><option v-for="c in dimCols" :key="c">{{ c }}</option></select>
          </div>
          <div class="form-group">
            <label class="form-label">Columns</label>
            <select v-model="colDim" class="form-input"><option value="">(none)</option><option v-for="c in dimCols" :key="c">{{ c }}</option></select>
          </div>
          <div class="form-group">
            <label class="form-label">From</label>
            <input v-model="from" type="date" class="form-input" />
          </div>
          <div class="form-group">
            <label class="form-label">To</label>
            <input v-model="to" type="date" class="form-input" />
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" @click="load">Load</button>
          <button class="btn btn-outline" :disabled="!pivot.rows.length" @click="exportCsv">Export CSV</button>
        </div>
        <div class="hint">{{ data.length }} records</div>
      </div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="card table-wrap" v-if="pivot.rows.length">
        <table class="pv">
          <thead>
            <tr><th>{{ rowDim }}</th><th v-for="c in pivot.cols" :key="c">{{ c }}</th><th>Total</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in pivot.rows" :key="r">
              <td class="pv__row">{{ r }}</td>
              <td v-for="c in pivot.cols" :key="c">{{ show(pivot.cell[r + '§' + c]) }}</td>
              <td class="pv__tot">{{ show(pivot.rowTot[r]) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr><td>Total</td><td v-for="c in pivot.cols" :key="c">{{ show(pivot.colTot[c]) }}</td><td>{{ show(pivot.grand) }}</td></tr>
          </tfoot>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { api } from '@/api/frappe'
import { today, daysAgo } from '@/utils'

const dataset = ref('inspection')
const from = ref(daysAgo(29))
const to = ref(today())
const data = ref([])
const loading = ref(false)
const error = ref('')
const measure = ref('__count')
const rowDim = ref('Checker')
const colDim = ref('Grade')

const cols = computed(() => data.value.length ? Object.keys(data.value[0]) : [])
const numericCols = computed(() => cols.value.filter(c => data.value.slice(0, 50).every(r => r[c] === null || typeof r[c] === 'number')))
const dimCols = computed(() => cols.value.filter(c => !numericCols.value.includes(c)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.pivotData(dataset.value, from.value, to.value)
    if (!dimCols.value.includes(rowDim.value)) rowDim.value = dataset.value === 'production' ? 'Operation' : 'Checker'
    if (colDim.value && !dimCols.value.includes(colDim.value)) colDim.value = ''
    if (measure.value !== '__count' && !numericCols.value.includes(measure.value)) measure.value = '__count'
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

const pivot = computed(() => {
  const cell = {}, rowTot = {}, colTot = {}
  let grand = 0
  const rows = new Set(), colsSet = new Set()
  for (const rec of data.value) {
    const r = String(rec[rowDim.value] ?? '-')
    const c = colDim.value ? String(rec[colDim.value] ?? '-') : 'Value'
    const v = measure.value === '__count' ? 1 : (Number(rec[measure.value]) || 0)
    rows.add(r); colsSet.add(c)
    cell[r + '§' + c] = (cell[r + '§' + c] || 0) + v
    rowTot[r] = (rowTot[r] || 0) + v
    colTot[c] = (colTot[c] || 0) + v
    grand += v
  }
  const rowList = [...rows].sort((a, b) => (rowTot[b] || 0) - (rowTot[a] || 0))
  const colList = [...colsSet].sort()
  return { rows: rowList, cols: colList, cell, rowTot, colTot, grand }
})

function show(v) {
  if (v === undefined) return ''
  return measure.value === '__count' ? v : Number(v).toFixed(2)
}

function exportCsv() {
  const p = pivot.value
  const lines = [[rowDim.value, ...p.cols, 'Total'].join(',')]
  for (const r of p.rows) lines.push([`"${r}"`, ...p.cols.map(c => show(p.cell[r + '§' + c])), show(p.rowTot[r])].join(','))
  lines.push(['Total', ...p.cols.map(c => show(p.colTot[c])), show(p.grand)].join(','))
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `pivot-${dataset.value}-${from.value}-${to.value}.csv`
  a.click()
}

onMounted(load)
</script>

<style scoped>
.wide { max-width: 1100px !important; }
.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 8px; }
.table-wrap { overflow-x: auto; padding: 0; }
.pv { border-collapse: collapse; width: 100%; font-size: 13px; }
.pv th, .pv td { padding: 8px 10px; border-bottom: 1px solid var(--slate-100); text-align: right; white-space: nowrap; }
.pv th:first-child, .pv td:first-child { text-align: left; position: sticky; left: 0; background: #fff; }
.pv thead th { background: var(--slate-50); font-size: 11px; text-transform: uppercase; color: var(--slate-500); }
.pv__tot, .pv tfoot td { font-weight: 800; }
</style>
