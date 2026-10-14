<template>
  <div class="as-root" ref="root">
    <input
      class="form-input"
      :placeholder="placeholder"
      :value="open ? query : (modelValue || '')"
      :disabled="disabled"
      @focus="onFocus"
      @input="onInput($event.target.value)"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="pick(options[hi])"
      @keydown.esc="open = false"
    />
    <button v-if="modelValue && !disabled" class="as-clear" type="button" @click="clear">✕</button>
    <div v-if="open" class="as-list">
      <div v-if="loading" class="as-empty">Searching…</div>
      <div v-else-if="!options.length" class="as-empty">No matches</div>
      <button
        v-for="(o, i) in options" :key="o.value" type="button"
        class="as-item" :class="{ 'as-item--hi': i === hi }"
        @mousedown.prevent="pick(o)"
      >
        <div class="as-item__label">{{ o.label || o.value }}</div>
        <div v-if="o.description" class="as-item__desc">{{ o.description }}</div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  fetcher: { type: Function, required: true }, // async (txt) => [{ value, label?, description? }]
  placeholder: { type: String, default: 'Search…' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'select'])

const root = ref(null)
const open = ref(false)
const query = ref('')
const options = ref([])
const loading = ref(false)
const hi = ref(0)
let timer = null
let seq = 0

async function load(txt) {
  const my = ++seq
  loading.value = true
  try {
    const rows = await props.fetcher(txt)
    if (my === seq) { options.value = rows || []; hi.value = 0 }
  } catch {
    if (my === seq) options.value = []
  } finally {
    if (my === seq) loading.value = false
  }
}

function onFocus() {
  open.value = true
  query.value = ''
  load('')
}
function onInput(v) {
  query.value = v
  open.value = true
  clearTimeout(timer)
  timer = setTimeout(() => load(v), 250)
}
function move(d) {
  if (!options.value.length) return
  hi.value = (hi.value + d + options.value.length) % options.value.length
}
function pick(o) {
  if (!o) return
  emit('update:modelValue', o.value)
  emit('select', o)
  open.value = false
}
function clear() {
  emit('update:modelValue', '')
  emit('select', null)
}
function onDocClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<style scoped>
.as-root { position: relative; }
.as-clear { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); border: none; background: none; color: #94a3b8; font-size: 14px; padding: 4px 6px; }
.as-list { position: absolute; z-index: 50; left: 0; right: 0; top: calc(100% + 4px); background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.12); max-height: 280px; overflow-y: auto; }
.as-item { display: block; width: 100%; text-align: left; border: none; background: none; padding: 10px 12px; border-bottom: 1px solid #f1f5f9; }
.as-item--hi, .as-item:hover { background: #f1f5f9; }
.as-item__label { font-size: 14px; font-weight: 600; color: #0f172a; overflow-wrap: anywhere; }
.as-item__desc { font-size: 12px; color: #64748b; margin-top: 2px; overflow-wrap: anywhere; }
.as-empty { padding: 12px; font-size: 13px; color: #94a3b8; text-align: center; }
</style>
