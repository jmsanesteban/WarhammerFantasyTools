// Warhammer Fantasy Tools — main.js

document.addEventListener('DOMContentLoaded', () => {
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
