const API = location.origin;

// util: fecha YYYY-MM-DD
const today = ()=> new Date().toISOString().slice(0,10);

// hash simple con SubtleCrypto
async function hashText(t) {
  const enc = new TextEncoder().encode(t);
  const buf = await crypto.subtle.digest('SHA-256', enc);
  return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
}

// pedir nombre/edad una vez por día (guardado localStorage)
async function ensureIdentity() {
  const key = 'visit-' + today();
  const cached = localStorage.getItem(key);
  if (cached) return JSON.parse(cached);

  let name = prompt('Tu nombre (solo para control de acceso del día):');
  let age = parseInt(prompt('Tu edad:'),10);
  if (!name) name = 'Invitado';
  if (!Number.isFinite(age)) age = 0;

  const user_hash = await hashText(name + '|' + age + '|' + today() + '|sal');
  const payload = { user_hash, name, age, date: today(), device_hint: navigator.userAgent.slice(0,80) };
  try { await fetch(API + '/visit', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)}); } catch {}

  const obj = {name, age, user_hash};
  localStorage.setItem(key, JSON.stringify(obj));
  return obj;
}

(async function init(){
  const ident = await ensureIdentity();
  const cfg = await fetch(API + '/config').then(r=>r.json());

  const map = L.map('map').setView([cfg.center_lat, cfg.center_lng], cfg.zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 20, attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // cargar pines existentes
  const pins = await fetch(API + '/pins').then(r=>r.json());
  const markerById = new Map();

  function iconFromEmoji(emoji) {
    return L.divIcon({className:'', html:`<div style="font-size:24px">${emoji}</div>`, iconSize:[24,24], iconAnchor:[12,12]});
  }

  function addMarker(pin) {
    const m = L.marker([pin.lat, pin.lng], {draggable:true, icon: iconFromEmoji(pin.type)}).addTo(map);
    m.on('dragend', async (e)=>{
      const {lat,lng} = e.target.getLatLng();
      await fetch(API + '/pins/' + pin.id, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lat,lng})});
    });
    m.on('click', ()=>{
      const info = pin.meta ? (()=>{ try{return JSON.parse(pin.meta);}catch{return {}} })() : {};
      const text = info && info.note ? info.note : 'Pin sin descripción';
      m.bindPopup(`<b>${pin.type}</b><div>${text}</div>`).openPopup();
    });
    markerById.set(pin.id, m);
  }

  pins.forEach(addMarker);

  // herramienta de “colocar pin”
  let currentType = '📍';
  document.querySelectorAll('.toolbar button').forEach(btn=>{
    btn.onclick = ()=> currentType = btn.dataset.pin;
  });

  map.on('click', async (e)=>{
    const note = prompt('Descripción breve para el pin (opcional):') || '';
    const body = {type: currentType, lat: e.latlng.lat, lng: e.latlng.lng, meta: {note}};
    const res = await fetch(API + '/pins', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const {id} = await res.json();
    addMarker({id, ...body, meta: JSON.stringify(body.meta)});
  });
})();
