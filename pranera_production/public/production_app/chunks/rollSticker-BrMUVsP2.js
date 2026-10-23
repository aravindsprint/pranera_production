import{b as m}from"./browser-CjSdxGTc.js";import{D as s}from"../index-BC0zZfzd.js";const r=t=>String(t??"").replace(/[&<>"]/g,o=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[o]);async function p(t){const o=`${t.item_code}#${t.work_order||t.batch||""}#${t.roll_no}`,e=t.item_code||"",i=e.length>28?"6.5pt":e.length>20?"7.5pt":"8.5pt",n=`${Number(t.weight||0).toFixed(3)} kg${t.qty?` · Qty: ${t.qty}`:""}${t.mistake_qty?` · Mistake: ${t.mistake_qty}`:""}${t.grade?` · G${t.grade}`:""}`,d=n.length>26?"6.5pt":n.length>20?"7.5pt":"8.5pt";let l="";try{l=await m.toDataURL(o,{width:200,margin:1})}catch(c){console.error("QR generation failed:",c)}return`<div class="sticker">
  <div class="qr-cell">${l?`<img src="${l}" style="width:24mm;height:24mm" alt="QR"/>`:""}</div>
  <table>
    <tr><td style="font-size:${i}">${r(e)}</td></tr>
    <tr><td>${r(t.commercial_name)}</td></tr>
    <tr><td>${r(t.work_order)}</td></tr>
    <tr><td>${r(t.roll_no)}</td></tr>
    <tr><td style="white-space:nowrap;font-size:${d}">${r(n)}</td></tr>
    ${t.batch?`<tr><td>${r(t.batch)}</td></tr>`:""}
  </table>
</div>`}function g(t){return`<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Roll Sticker${t.length>1?"s":""}</title>
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
${t.join(`
`)}
<div class="noprint">
  <button class="btn-p" onclick="window.print()">🖨 Print${t.length>1?` All (${t.length})`:""}</button>
  <button class="btn-c" onclick="window.close()">Close</button>
</div>
</body></html>`}async function w({rolls:t,stock_entry:o}){const e=window.open("","_blank");if(!e)throw new Error("Allow pop-ups to print stickers.");e.document.write('<p style="font-family:Arial;padding:20px">Preparing stickers…</p>');try{const i=(await s("pranera_production.api.rolls.get_sticker_data",o?{stock_entry:o}:{rolls:t})).message||[],a=[];for(const n of i)a.push(await p(n));e.document.open(),e.document.write(g(a)),e.document.close()}catch(i){throw e.close(),i}}export{w as p};
