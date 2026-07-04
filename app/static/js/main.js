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
});
