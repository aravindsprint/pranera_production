<template>
  <div class="page">
    <AppHeader title="My Pick Orders" subtitle="Lot section → Job Card" active="my-pick-orders" :show-back="true" />
    <div class="page-content">
      <label v-if="auth.can()" class="all-toggle">
        <input type="checkbox" v-model="showAll" @change="load" /> Show everyone's open orders
      </label>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <div v-else-if="!orders.length" class="empty-state">
        <div class="empty-state__icon">✅</div>
        <div class="empty-state__title">No pick orders right now</div>
      </div>
      <button v-for="o in orders" :key="o.name" class="card order" @click="open(o.name)">
        <div class="order__top">
          <span class="order__name">{{ o.name }}</span>
          <span class="badge" :class="statusClass(o.status)">{{ o.status }}</span>
        </div>
        <div class="order__doc">{{ o.work_order }} · {{ o.operation || '' }} · {{ o.job_card }}</div>
        <div class="order__item">{{ o.production_item }}</div>
        <div class="order__wh">{{ o.source_warehouse }} → {{ o.target_warehouse }}</div>
        <div class="order__meta">
          <span>{{ o.picked_rolls || 0 }} roll(s)</span>
          <span>{{ fmt(o.picked_qty) }} / {{ fmt(o.pick_qty) }}</span>
          <span>{{ o.posting_date }}</span>
          <span v-if="showAll">{{ o.assigned_to }}</span>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/frappe'
import { BASE, fmt, statusClass } from '@/utils'

const auth = useAuthStore()
const router = useRouter()
const orders = ref([])
const loading = ref(false)
const error = ref('')
const showAll = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    orders.value = await api.myPickOrders(showAll.value ? 1 : 0)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
function open(name) { router.push({ path: BASE + '/pick-execution', query: { order: name } }) }
onMounted(load)
</script>

<style scoped>
.all-toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 12px; color: var(--slate-700); }
.order { display: block; width: 100%; text-align: left; }
.order__top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.order__name { font-weight: 800; }
.order__doc { font-size: 13px; color: var(--slate-700); margin-top: 4px; overflow-wrap: anywhere; }
.order__item { font-size: 12px; color: var(--slate-500); overflow-wrap: anywhere; }
.order__wh { font-size: 12px; color: var(--slate-500); margin-top: 4px; overflow-wrap: anywhere; }
.order__meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; font-weight: 600; margin-top: 8px; color: var(--slate-700); }
</style>
