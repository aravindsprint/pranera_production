<template>
  <div class="ba">
    <div v-if="loading" class="ba__hint">Loading batches…</div>
    <div v-else-if="noCacheOffline" class="ba__hint">Offline — batches will be picked oldest-first (FIFO) when this is sent to ERPNext.</div>
    <div v-else-if="error" class="ba__err">{{ error }}</div>
    <template v-else-if="info">
      <div v-if="offlineAt" class="ba__hint">Offline — stock as of {{ new Date(offlineAt).toLocaleString() }}. If a batch has run out by the time this is sent, the oldest batch with stock is used.</div>
      <div v-if="!info.batches.length" class="ba__err">No stock in {{ info.warehouse }}</div>
      <template v-else-if="info.has_batch_no">
        <div class="ba__row" v-for="(r, i) in rows" :key="i">
          <select v-model="r.batch_no" class="form-input ba__batch" @change="touched = true; emitRows()">
            <option v-for="b in info.batches" :key="b.batch_no" :value="b.batch_no">{{ b.batch_no }} · {{ fmt(b.qty, 3) }}</option>
          </select>
          <input v-model.number="r.qty" type="number" step="0.001" class="form-input ba__qty" @input="touched = true; emitRows()" />
          <button type="button" class="ba__x" title="Remove" @click="rows.splice(i, 1); touched = true; emitRows()">✕</button>
        </div>
        <div class="ba__foot">
          <button type="button" class="btn btn-ghost ba__btn" @click="addRow">+ Batch</button>
          <button v-if="touched" type="button" class="btn btn-ghost ba__btn" @click="fifo">Reset to FIFO</button>
          <span class="ba__sum" :class="{ bad: Math.abs(total - (qty || 0)) > 0.0015 }">
            {{ fmt(total, 3) }} / {{ fmt(qty || 0, 3) }} {{ info.stock_uom }}
          </span>
        </div>
        <div class="ba__hint">Oldest batch first (FIFO) is filled in; change it if you're using another batch.</div>
      </template>
      <div v-else class="ba__hint">{{ fmt(info.batches[0].qty, 3) }} {{ info.stock_uom }} in stock (no batches)</div>
    </template>
  </div>
</template>

<script setup>
// Batch picker for a chemical issue: FIFO allocation of `qty` is suggested,
// the user may change batches / split quantities. Emits [{ batch_no, qty }].
import { ref, computed, watch } from 'vue'
import { api } from '@/api/frappe'
import { cached } from '@/composables/useOffline'
import { fmt } from '@/utils'

const props = defineProps({
  itemCode: { type: String, required: true },
  warehouse: { type: String, default: '' },
  qty: { type: Number, default: 0 },
})
const emit = defineEmits(['update:allocations'])

const info = ref(null)
const rows = ref([])
const loading = ref(false)
const error = ref('')
const touched = ref(false)
const offlineAt = ref(null)
const noCacheOffline = ref(false)
const total = computed(() => rows.value.reduce((s, r) => s + (Number(r.qty) || 0), 0))

function emitRows() {
  emit('update:allocations', info.value?.has_batch_no
    ? rows.value.filter(r => r.batch_no && Number(r.qty) > 0).map(r => ({ batch_no: r.batch_no, qty: Number(r.qty) }))
    : [])
}

function fifo() {
  touched.value = false
  const out = []
  let left = Math.floor((Number(props.qty) || 0) * 1000) / 1000
  for (const b of info.value?.batches || []) {
    if (left <= 0) break
    const take = Math.floor(Math.min(b.qty, left) * 1000) / 1000
    if (take > 0) { out.push({ batch_no: b.batch_no, qty: take }); left = Math.round((left - take) * 1000) / 1000 }
  }
  rows.value = out
  emitRows()
}

function addRow() {
  const used = new Set(rows.value.map(r => r.batch_no))
  const next = (info.value?.batches || []).find(b => !used.has(b.batch_no))
  rows.value.push({ batch_no: next?.batch_no || '', qty: 0 })
  touched.value = true
}

async function load() {
  if (!props.itemCode) return
  loading.value = true
  error.value = ''
  noCacheOffline.value = false
  try {
    const r = await cached(`batches:${props.itemCode}:${props.warehouse || ''}`,
      () => api.dyeBatches(props.itemCode, props.warehouse || undefined))
    info.value = r.data
    offlineAt.value = r.offline ? r.at : null
    fifo()
  } catch (err) {
    info.value = null
    if (/Failed to fetch|NetworkError|Load failed|network|BackendUnreachable/i.test(err.message || '')) {
      noCacheOffline.value = true
      emit('update:allocations', [])
    } else error.value = err.message
  } finally {
    loading.value = false
  }
}

watch(() => [props.itemCode, props.warehouse], load, { immediate: true })
// a new quantity re-suggests FIFO unless the user picked batches by hand
watch(() => props.qty, () => { if (!touched.value && info.value) fifo() })
</script>

<style scoped>
.ba { margin-top: 8px; }
.ba__row { display: flex; gap: 6px; margin-bottom: 6px; align-items: center; }
.ba__batch { flex: 1; min-width: 0; font-size: 13px; }
.ba__qty { width: 96px; flex-shrink: 0; }
.ba__x { border: none; background: none; color: var(--slate-400); font-size: 14px; padding: 4px 6px; cursor: pointer; }
.ba__foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ba__btn { padding: 4px 8px; font-size: 12px; }
.ba__sum { margin-left: auto; font-size: 12px; font-weight: 700; color: var(--emerald-700); }
.ba__sum.bad { color: var(--red-600); }
.ba__hint { font-size: 11.5px; color: var(--slate-500); margin-top: 4px; }
.ba__err { font-size: 12px; color: var(--red-600); }
</style>
