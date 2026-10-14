<template>
  <div class="page">
    <AppHeader title="Inspection" subtitle="INSPECTION job cards" active="inspection" />
    <div class="page-content">
      <div class="filters">
        <input v-model="txt" class="form-input" placeholder="Search job card / WO / item" @input="debounced" />
        <label class="chk"><input type="checkbox" v-model="includeCompleted" @change="load" /> Include completed</label>
      </div>
      <div v-if="offline" class="alert alert-warning">Offline — showing the last loaded list.</div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="!rows.length" class="empty-state"><div class="empty-state__icon">🔍</div><div class="empty-state__title">No inspection job cards</div></div>
      <button v-for="j in rows" :key="j.name" class="card jc" @click="router.push(BASE + '/inspection/' + encodeURIComponent(j.name))">
        <div class="jc__top"><b>{{ j.name }}</b><span class="badge" :class="statusClass(j.status)">{{ j.status }}</span></div>
        <div class="jc__meta">{{ j.work_order }} · {{ j.workstation }}</div>
        <div class="jc__meta">{{ j.production_item }}<span v-if="j.color"> · {{ j.color }}</span></div>
        <div class="jc__nums">
          <span>Inspected {{ j.custom_inspected_rolls || 0 }} rolls · {{ fmt(j.custom_inspected_weight) }} kg</span>
          <span class="badge badge-info" v-if="j.rolls_in_process">{{ j.rolls_in_process }} in process</span>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { api } from '@/api/frappe'
import { BASE, fmt, statusClass } from '@/utils'

const router = useRouter()
const rows = ref(JSON.parse(localStorage.getItem('PROD_INSP_LIST') || '[]'))
const loading = ref(false)
const offline = ref(false)
const txt = ref('')
const includeCompleted = ref(false)
let t = null

async function load() {
  loading.value = !rows.value.length
  try {
    rows.value = await api.inspectionJobCards(txt.value || undefined, includeCompleted.value ? 1 : 0)
    if (!txt.value && !includeCompleted.value) localStorage.setItem('PROD_INSP_LIST', JSON.stringify(rows.value))
    offline.value = false
  } catch {
    offline.value = true
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
.jc__nums { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; margin-top: 8px; align-items: center; }
</style>
