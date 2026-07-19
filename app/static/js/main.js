// Warhammer Fantasy Tools — main.js

document.addEventListener('DOMContentLoaded', () => {
  // Theme toggle (Modo oscuro / Modo claro): the actual data-theme attribute
  // is already set as early as possible by an inline script in base.html's
  // <head> (before first paint, to avoid a flash of the wrong theme) - this
  // just wires the two menu buttons and keeps their checkmark in sync.
  function whApplyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('.wh-theme-option').forEach(btn => {
      btn.classList.toggle('wh-theme-active', btn.dataset.whTheme === theme);
    });
  }
  document.querySelectorAll('.wh-theme-option').forEach(btn => {
    btn.addEventListener('click', () => {
      const theme = btn.dataset.whTheme;
      localStorage.setItem('wh-theme', theme);
      whApplyTheme(theme);
    });
  });
  whApplyTheme(localStorage.getItem('wh-theme') || 'dark');

  // Auto-dismiss flash alerts after 5 seconds
  document.querySelectorAll('.alert.alert-dismissible').forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 5000);
  });

  // Confirm delete forms already handled inline via onsubmit

  // Pathfinder: pre-select from URL params
  const params = new URLSearchParams(window.location.search);
  const startId = params.get('start_id');
  if (startId) {
    const sel = document.querySelector('select[name="start_id"]');
    if (sel) sel.value = startId;
  }

  // Characteristic input validation: primary must be multiples of 5
  document.querySelectorAll('input[step="5"]').forEach(input => {
    input.addEventListener('change', () => {
      const val = parseInt(input.value, 10);
      if (!isNaN(val) && val % 5 !== 0) {
        input.value = Math.round(val / 5) * 5;
      }
    });
  });

  // Equipment images: click to open a full-size lightbox (complements the
  // hover-zoom in custom.css, which is only meant as a quick peek).
  // Delegated on `document` (2026-07-19) rather than bound per-image at load
  // time, so it keeps working for `.wh-lightbox-trigger` images swapped into
  // the page later (e.g. the Contactos live-search result fragment) without
  // needing to re-wire anything after each swap.
  const lightbox = document.getElementById('whLightbox');
  const lightboxImg = lightbox ? lightbox.querySelector('img') : null;
  if (lightbox && lightboxImg) {
    document.addEventListener('click', e => {
      const img = e.target.closest('.wh-lightbox-trigger');
      if (!img) return;
      lightboxImg.src = img.src;
      lightboxImg.alt = img.alt;
      lightbox.classList.add('wh-lightbox-open');
    });
    const closeLightbox = () => lightbox.classList.remove('wh-lightbox-open');
    lightbox.addEventListener('click', closeLightbox);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeLightbox();
    });
  }

  // Untersuchung grado picker (characters/form.html, propia pertenencia del
  // personaje a la Untersuchung - separado de Contactos desde 2026-07-19,
  // ver TIPO_RELACION_CHOICES): 3 independent slots.
  initGradoPicker();

  // Tipo de relación (contacts/detail.html): checkboxes marcados con el
  // mismo data-exclusive-group son mutuamente excluyentes (Súbdito/Señor -
  // ver TIPO_RELACION_EXCLUSIVE_PAIRS) - marcar uno desmarca su pareja. El
  // servidor aplica la misma regla igualmente (_dedupe_tipo_relacion), esto
  // es solo para no dejar que el usuario marque ambos y luego se sorprenda
  // al ver que uno desaparece al guardar.
  document.querySelectorAll('.wh-exclusive-cb[data-exclusive-group]').forEach(cb => {
    cb.addEventListener('change', () => {
      if (!cb.checked) return;
      document.querySelectorAll(
        `.wh-exclusive-cb[data-exclusive-group="${cb.dataset.exclusiveGroup}"]`
      ).forEach(other => {
        if (other !== cb) other.checked = false;
      });
    });
  });

  // Contactos: drag-to-reorder field definitions
  const fieldsTbody = document.getElementById('fieldsTbody');
  if (fieldsTbody) {
    let dragging = null;
    fieldsTbody.querySelectorAll('.draggable-row').forEach(row => {
      row.draggable = true;
      row.addEventListener('dragstart', () => { dragging = row; row.classList.add('opacity-50'); });
      row.addEventListener('dragend', () => { row.classList.remove('opacity-50'); saveFieldOrder(fieldsTbody); });
      row.addEventListener('dragover', e => {
        e.preventDefault();
        const after = getDragAfterElement(fieldsTbody, e.clientY);
        if (after == null) fieldsTbody.appendChild(dragging);
        else fieldsTbody.insertBefore(dragging, after);
      });
    });
  }
});

// ── Untersuchung grado picker ────────────────────────────────────────────────
// Slots 2/3 no longer offer Adjunto options at all (only slot 1's <select>
// has that <optgroup> - see contacts/new.html etc.), so the only rule left
// to enforce client-side is: if slot 1 holds an Adjunto value (Carro/
// Paloma - capped at exactly 1 mark, server-enforced by clamp_grados()),
// slots 2 and 3 are irrelevant and get disabled + cleared.
function initGradoPicker() {
  const slots = Array.from(document.querySelectorAll('.grado-slot'));
  if (!slots.length) return;
  const preview = document.getElementById('marcas-preview');
  const untersuchungChk = document.getElementById('chk-untersuchung');
  const selectedOption = slot => slot.options[slot.selectedIndex];
  function sync() {
    const first = selectedOption(slots[0]);
    const firstIsAdjunto = Boolean(first.value) && first.dataset.tier === 'adjunto';
    slots.forEach((s, i) => {
      if (i === 0) return;
      s.disabled = firstIsAdjunto;
      if (s.disabled) s.value = '';
    });
    if (preview) {
      preview.innerHTML = '';
      slots.map(selectedOption).filter(o => o.value).forEach(o => {
        if (!o.dataset.marca) return;
        const img = document.createElement('img');
        img.src = o.dataset.marca;
        img.alt = o.value;
        img.title = o.value;
        img.style.cssText = 'width:64px;height:64px;object-fit:cover;border-radius:4px;border:1px solid var(--wh-border-gold)';
        preview.appendChild(img);
      });
    }
    if (untersuchungChk && slots.some(s => selectedOption(s).value)) {
      untersuchungChk.checked = true;
    }
  }
  slots.forEach(s => s.addEventListener('change', sync));
  sync();
}

// ── Contactos helpers ────────────────────────────────────────────────────────

function getCsrfToken() {
  const input = document.querySelector('input[name="csrf_token"]');
  return input ? input.value : '';
}

function getDragAfterElement(container, y) {
  const els = [...container.querySelectorAll('.draggable-row:not(.opacity-50)')];
  return els.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    return offset < 0 && offset > closest.offset ? { offset, element: child } : closest;
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

async function saveFieldOrder(tbody) {
  const order = [...tbody.querySelectorAll('.draggable-row')].map(r => parseInt(r.dataset.id, 10));
  await fetch(tbody.dataset.reorderUrl, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ order }),
  });
}

async function toggleFieldVisibility(btn) {
  const res = await fetch(btn.dataset.url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
  });
  const data = await res.json();
  const id = btn.dataset.id;
  const icon = btn.querySelector('i');
  btn.classList.toggle('btn-outline-secondary', data.visible);
  btn.classList.toggle('btn-outline-warning', !data.visible);
  if (icon) {
    icon.classList.toggle('bi-eye', data.visible);
    icon.classList.toggle('bi-eye-slash', !data.visible);
  }
  const badge = document.querySelector(`.visibility-badge-${id}`);
  if (badge) {
    badge.textContent = data.visible ? 'Visible' : 'Oculto';
    badge.className = `badge ${data.visible ? 'bg-success' : 'bg-secondary'} visibility-badge-${id}`;
  }
}

async function toggleContactVisibility(btn) {
  const res = await fetch(btn.dataset.url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
  });
  const data = await res.json();
  const icon = btn.querySelector('i');
  btn.classList.toggle('btn-outline-secondary', data.visible);
  btn.classList.toggle('btn-outline-warning', !data.visible);
  if (icon) {
    icon.classList.toggle('bi-eye', data.visible);
    icon.classList.toggle('bi-eye-slash', !data.visible);
  }
}
