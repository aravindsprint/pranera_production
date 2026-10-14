<template>
  <div class="page">
    <AppHeader title="Production" subtitle="Pranera — Process Floor" active="home" />
    <div class="page-content">
      <div class="hello card">
        <div class="hello__name">Hi {{ auth.username || 'there' }}</div>
        <div class="hello__roles">
          <span v-for="r in auth.info?.roles || []" :key="r" class="badge badge-secondary">{{ r }}</span>
        </div>
      </div>

      <div class="tiles">
        <button v-for="t in tiles" :key="t.path" class="tile" @click="router.push(t.path)">
          <span class="tile__icon">{{ t.icon }}</span>
          <span class="tile__label">{{ t.label }}</span>
          <span class="tile__sub">{{ t.sub }}</span>
          <span v-if="t.count" class="tile__count">{{ t.count }}</span>
        </button>
      </div>

      <div class="card" v-if="inProcess.length">
        <div class="section-title">Rolls in process now</div>
        <div class="ip-row" v-for="p in inProcess" :key="p.label">
          <span class="ip-op">{{ p.label }}</span>
          <span class="ip-n">{{ p.rolls }} rolls</span>
          <span class="ip-w">{{ fmt(p.weight) }} kg</span>
        </div>
      </div>

      <div v-if="pendingCount" class="alert alert-warning">
        {{ pendingCount }} inspection save(s) waiting to sync — they will upload automatically when the connection is back.
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/frappe'
import { pendingCount } from '@/composables/useSync'
import { BASE, fmt, today } from '@/utils'

const auth = useAuthStore()
const router = useRouter()
const myOrders = ref(0)
const inProcess = ref([])

const tiles = computed(() => {
  const c = (...r) => auth.can(...r)
  return [
    c('Roll Picker') && { icon: '✅', label: 'My Pick Orders', sub: 'Fabric / collar / cuff to job card', path: BASE + '/my-pick-orders', count: myOrders.value },
    c('Chemical Issuer') && { icon: '🧪', label: 'Chemical Issue', sub: 'Dyes & chemicals from Dye Chart', path: BASE + '/chemical-issue' },
    c('Process Operator') && { icon: '⚙️', label: 'Job Cards', sub: 'Start / complete operations', path: BASE + '/job-cards' },
    c('Process Operator') && { icon: '🏭', label: 'Manufacture', sub: 'MF from rolls (partial allowed)', path: BASE + '/manufacture' },
    c('Inspection Checker') && { icon: '🔍', label: 'Inspection', sub: 'Fabric & collar/cuff, 4-point', path: BASE + '/inspection' },
    c() && { icon: '📝', label: 'Create Pick Order', sub: 'Assign a lot pick to a worker', path: BASE + '/create-pick-order' },
    { icon: '🧶', label: 'Roll Trace', sub: 'Where is a roll, what happened', path: BASE + '/rolls' },
    c('Inspection Checker', 'Process Operator') && { icon: '📈', label: 'Dashboard', sub: 'Inspection & production', path: BASE + '/dashboard' },
  ].filter(Boolean)
})

async function load() {
  if (!auth.info) return
  if (!auth.hasAccess) { router.replace(BASE + '/no-access'); return }
  try {
    if (auth.can('Roll Picker')) myOrders.value = (await api.myPickOrders()).length
  } catch { /* offline */ }
  try {
    if (auth.can('Process Operator', 'Inspection Checker')) {
      const d = await api.dashboard(today(), today())
      inProcess.value = d?.production?.in_process || []
    }
  } catch { /* offline */ }
}

onMounted(load)
watch(() => auth.info, load)
</script>

<style scoped>
.hello__name { font-size: 18px; font-weight: 800; }
.hello__roles { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
@media (min-width: 768px) { .tiles { grid-template-columns: repeat(3, 1fr); } }
.tile { position: relative; background: #fff; border: 1px solid var(--slate-200); border-radius: 16px; padding: 16px 14px; text-align: left; display: flex; flex-direction: column; gap: 4px; box-shadow: var(--shadow-sm); min-height: 116px; }
.tile:active { transform: scale(0.98); }
.tile__icon { font-size: 26px; }
.tile__label { font-size: 15px; font-weight: 700; color: var(--slate-900); }
.tile__sub { font-size: 12px; color: var(--slate-500); line-height: 1.35; }
.tile__count { position: absolute; top: 10px; right: 10px; background: var(--app-primary); color: #fff; border-radius: 20px; font-size: 12px; font-weight: 700; padding: 2px 9px; }
.ip-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--slate-100); font-size: 14px; }
.ip-op { flex: 1; font-weight: 600; }
.ip-n { color: var(--slate-500); }
.ip-w { font-weight: 700; min-width: 90px; text-align: right; }
</style>
