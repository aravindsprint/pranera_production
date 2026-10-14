<template>
  <transition name="modal-fade">
    <div v-if="modelValue" class="sm-overlay" @click.self="close">
      <div class="sm-box">
        <h3 class="sm-title">{{ title }}</h3>
        <div :id="regionId" class="sm-camera"></div>
        <div v-if="cameraError" class="sm-error">{{ cameraError }}</div>
        <form v-if="allowManual" class="sm-manual" @submit.prevent="submitManual">
          <input v-model="manual" class="form-input" placeholder="Or type the roll no" inputmode="text" />
          <button class="btn btn-primary" type="submit" :disabled="!manual.trim()">Go</button>
        </form>
        <button class="btn btn-ghost btn-full" style="margin-top:12px" @click="close">Cancel</button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { Html5Qrcode } from 'html5-qrcode'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: 'Scan Roll' },
  allowManual: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'scanned'])

const regionId = 'scan-' + Math.random().toString(36).slice(2, 9)
const cameraError = ref('')
const manual = ref('')
let qr = null

async function start() {
  cameraError.value = ''
  await nextTick()
  try {
    qr = new Html5Qrcode(regionId)
    await qr.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
      onDecoded,
      () => {}
    )
  } catch (err) {
    cameraError.value = 'Could not access the camera: ' + (err?.message || err)
  }
}

async function stop() {
  if (!qr) return
  try {
    if (qr.isScanning) await qr.stop()
    qr.clear()
  } catch { /* ignore */ }
  qr = null
}

async function onDecoded(text) {
  await stop()
  emit('update:modelValue', false)
  emit('scanned', String(text).trim())
}

async function submitManual() {
  const v = manual.value.trim()
  if (!v) return
  manual.value = ''
  await stop()
  emit('update:modelValue', false)
  emit('scanned', v)
}

async function close() {
  await stop()
  emit('update:modelValue', false)
}

watch(() => props.modelValue, (open) => { open ? start() : stop() })
onBeforeUnmount(stop)
</script>

<style scoped>
.sm-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.6); display: flex; align-items: center; justify-content: center; z-index: 600; padding: 16px; }
.sm-box { background: #fff; border-radius: 14px; padding: 20px; width: 100%; max-width: 420px; }
.sm-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; text-align: center; }
.sm-camera { width: 100%; aspect-ratio: 1 / 1; border-radius: 10px; overflow: hidden; background: #0f172a; }
.sm-camera :deep(video) { width: 100% !important; height: 100% !important; object-fit: cover !important; }
.sm-error { margin-top: 10px; background: #fee2e2; color: #991b1b; padding: 10px; border-radius: 8px; font-size: 13px; }
.sm-manual { display: flex; gap: 8px; margin-top: 12px; }
.sm-manual .form-input { flex: 1; }
.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.2s; }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
</style>
