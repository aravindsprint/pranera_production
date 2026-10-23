// Roll stickers — the same 50 × 65 mm label the Rolls page has always
// printed (QR on top, then item / commercial name / work order / roll /
// weight / batch), filled from the roll's CURRENT state, so a dyed or
// finished roll gets its new item and batch.
import QRCode from 'qrcode'
import { call } from '@/api/frappe'

const esc = (v) => String(v ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

// s: { roll_no, item_code, commercial_name, work_order, batch, weight, qty, mistake_qty, grade }
export async function stickerDiv(s) {
  // scanners read the last "#" part as the roll no (item#reference#roll)
  const qrData = `${s.item_code}#${s.work_order || s.batch || ''}#${s.roll_no}`
  const itemCode = s.item_code || ''
  const itemFontSize = itemCode.length > 28 ? '6.5pt' : (itemCode.length > 20 ? '7.5pt' : '8.5pt')
  const weight = Number(s.weight || 0).toFixed(3)
  const weightLine = `${weight} kg${s.qty ? ` · Qty: ${s.qty}` : ''}${s.mistake_qty ? ` · Mistake: ${s.mistake_qty}` : ''}${s.grade ? ` · G${s.grade}` : ''}`
  const weightFontSize = weightLine.length > 26 ? '6.5pt' : (weightLine.length > 20 ? '7.5pt' : '8.5pt')
  let qrImg = ''
  try { qrImg = await QRCode.toDataURL(qrData, { width: 200, margin: 1 }) } catch (e) { console.error('QR generation failed:', e) }
  return `<div class="sticker">
  <div class="qr-cell">${qrImg ? `<img src="${qrImg}" style="width:24mm;height:24mm" alt="QR"/>` : ''}</div>
  <table>
    <tr><td style="font-size:${itemFontSize}">${esc(itemCode)}</td></tr>
    <tr><td>${esc(s.commercial_name)}</td></tr>
    <tr><td>${esc(s.work_order)}</td></tr>
    <tr><td>${esc(s.roll_no)}</td></tr>
    <tr><td style="white-space:nowrap;font-size:${weightFontSize}">${esc(weightLine)}</td></tr>
    ${s.batch ? `<tr><td>${esc(s.batch)}</td></tr>` : ''}
  </table>
</div>`
}

export function stickerWindowHtml(divs) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Roll Sticker${divs.length > 1 ? 's' : ''}</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:100%; }
  body { font-family:Arial,sans-serif; display:flex; flex-direction:column; align-items:center; }
  .sticker { width:50mm; min-height:65mm; border:1px solid #000; display:flex;
             margin:2mm auto; flex-direction:column; flex-shrink:0; }
  .qr-cell { display:flex; align-items:center; justify-content:center; padding:2mm;
             border-bottom:1px solid #000; flex:0 0 auto; }
  table { width:calc(100% - 0.5cm); margin-left:0.5cm; border-collapse:collapse; flex:1; }
  td { padding:1.1mm 3mm; border-bottom:1px solid #000; font-size:8.5pt; font-weight:800;
       font-family:Arial,Helvetica,sans-serif; color:#000; line-height:1.15;
       word-break:break-word; white-space:normal; overflow-wrap:break-word; }
  tr:last-child td { border-bottom:none; padding-bottom:1.5mm; }
  .noprint { text-align:center; padding:10px; }
  .noprint button { padding:7px 18px; margin:0 4px; border-radius:5px; border:none;
    cursor:pointer; font-size:12px; font-weight:600; }
  .btn-p { background:#000; color:#fff; }
  .btn-c { background:#eee; color:#333; }
  @media print {
    .noprint { display:none; }
    body { display:block; }
    .sticker { margin:2mm auto 0; max-height:73mm; overflow:hidden; }
    .sticker:not(:last-child) { page-break-after: always; }
    @page { size:60mm 75mm; margin:0; }
  }
</style>
</head><body>
${divs.join('\n')}
<div class="noprint">
  <button class="btn-p" onclick="window.print()">🖨 Print${divs.length > 1 ? ` All (${divs.length})` : ''}</button>
  <button class="btn-c" onclick="window.close()">Close</button>
</div>
</body></html>`
}

// Open the print window for { rolls: [...] } or { stock_entry: 'MF/26/…' }.
// The window is opened first (synchronously, inside the click) so pop-up
// blockers allow it, then filled once the data is in.
export async function printRollStickers({ rolls, stock_entry }) {
  const w = window.open('', '_blank')
  if (!w) throw new Error('Allow pop-ups to print stickers.')
  w.document.write('<p style="font-family:Arial;padding:20px">Preparing stickers…</p>')
  try {
    const data = (await call('pranera_production.api.rolls.get_sticker_data',
      stock_entry ? { stock_entry } : { rolls })).message || []
    const divs = []
    for (const s of data) divs.push(await stickerDiv(s))
    w.document.open()
    w.document.write(stickerWindowHtml(divs))
    w.document.close()
  } catch (e) {
    w.close()
    throw e
  }
}
