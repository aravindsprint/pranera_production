<template>
  <div class="page">
    <AppHeader title="Job Cards" subtitle="Operations on the floor" active="job-cards" />
    <div class="page-content">
      <div class="filters">
        <input v-model="txt" class="form-input" placeholder="Search job card / WO / item" @input="debounced" />
        <select v-model="operation" class="form-input" @change="load">
          <option value="">All operations</option>
          <option v-for="o in operations" :key="o" :value="o">{{ o }}</option>
        </select>
        <label class="chk"><input type="checkbox" v-model="withRolls" /> Only with rolls in process</label>
      </div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <div v-if="offlineAt" class="alert alert-warning">Offline — list as of {{ new Date(offlineAt).toLocaleString() }}. Job Cards opened while online can be started and ended offline.</div>
      <div v-else-if="!shown.length" class="empty-state"><div class="empty-state__icon">⚙️</div><div class="empty-state__title">Nothing here</div></div>
      <button v-for="j in shown" :key="j.name" class="card jc" @click="router.push(BASE + '/job-cards/' + encodeURIComponent(j.name))">
        <div class="jc__top">
          <b>{{ j.operation }}</b>
          <span class="badge" :class="statusClass(j.status)">{{ j.status }}</span>
        </div>
        <div class="jc__meta">{{ j.name }} · {{ j.workstation }}</div>
        <div class="jc__meta">{{ j.work_order }} · {{ j.production_item }}<span v-if="j.color"> · {{ j.color }}</span></div>
        <div class="jc__nums">
          <span>For {{ fmt(j.for_quantity) }}</span>
          <span>Transferred {{ fmt(j.transferred_qty) }}</span>
          <span v-if="j.rolls_in_process" class="badge badge-info">{{ j.rolls_in_process }} rolls · {{ fmt(j.weight_in_process) }} kg</span>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { api } from '@/api/frappe'
import { cached } from '@/composables/useOffline'
import { BASE, fmt, statusClass } from '@/utils'

const router = useRouter()
const rows = ref([])
const loading = ref(false)
const error = ref('')
const txt = ref('')
const operation = ref(localStorage.getItem('PROD_JC_OP') || '')
const withRolls = ref(false)
const offlineAt = ref(null)
let t = null

const operations = computed(() => [...new Set(rows.value.map(r => r.operation).concat(operation.value ? [operation.value] : []))].filter(Boolean).sort())
const shown = computed(() => withRolls.value ? rows.value.filter(r => r.rolls_in_process) : rows.value)

async function load() {
  localStorage.setItem('PROD_JC_OP', operation.value)
  loading.value = true
  error.value = ''
  try {
    const r = await cached('jcs:' + (operation.value || '') + ':' + (txt.value || ''),
      () => api.jobCards({ txt: txt.value || undefined, operation: operation.value || undefined }))
    rows.value = r.data
    offlineAt.value = r.offline ? r.at : null
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
function debounced() { clearTimeout(t); t = setTimeout(load, 300) }
onMounted(load)
</script>

<style scoped>
.filters { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.chk { font-size: 13px; display: flex; gap: 8px; align-items: center; color: var(--slate-700); }
.jc { display: block; width: 100%; text-align: left; }
.jc__top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.jc__meta { font-size: 12px; color: var(--slate-500); margin-top: 3px; overflow-wrap: anywhere; }
.jc__nums { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; margin-top: 8px; color: var(--slate-700); align-items: center; }
</style>
