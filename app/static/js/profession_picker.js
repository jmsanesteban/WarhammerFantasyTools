// Searchable profession combobox used in character creation/editing.
// A text input + dropdown over the full profession catalog (never filtered
// out — every profession stays selectable), with career-exit professions
// (from professions already chosen elsewhere on the same page) marked
// visually so they stand out without restricting the choice.

class ProfessionPicker {
  constructor(root, { options, getHighlightIds }) {
    this.root = root;
    this.options = options; // [{id, name}], expected pre-sorted alphabetically
    this.getHighlightIds = getHighlightIds || (() => new Set());
    this.hidden = root.querySelector('.prof-picker-hidden');
    this.input = root.querySelector('.prof-picker-input');
    this.dropdown = root.querySelector('.prof-picker-dropdown');
    this._bind();
  }

  static _normalize(s) {
    return (s || '').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  _bind() {
    this.input.addEventListener('input', () => {
      if (this.input.value === '') this.hidden.value = '';
      this._render();
    });
    this.input.addEventListener('focus', () => this._render());
    this.input.addEventListener('blur', () => {
      // Delay so a dropdown-item click (mousedown) still registers first.
      setTimeout(() => this._close(), 150);
    });
    this.dropdown.addEventListener('mousedown', (e) => {
      const item = e.target.closest('.prof-picker-option');
      if (!item) return;
      e.preventDefault();
      this._select(item.dataset.id, item.dataset.name);
    });
  }

  _select(id, name) {
    this.hidden.value = id;
    this.input.value = name;
    this._close();
    this.root.dispatchEvent(new CustomEvent('prof-picker:change', { bubbles: true }));
  }

  /** Programmatic selection (e.g. after a dice-roll result), same effect as picking from the dropdown. */
  selectById(id, name) {
    this._select(id, name);
  }

  _close() {
    this.dropdown.classList.remove('open');
    this.dropdown.innerHTML = '';
  }

  _render() {
    const query = ProfessionPicker._normalize(this.input.value);
    const matches = query
      ? this.options.filter(o => ProfessionPicker._normalize(o.name).includes(query))
      : this.options;

    if (!matches.length) {
      this.dropdown.innerHTML = '<div class="prof-picker-empty small px-2 py-1">Sin coincidencias</div>';
      this.dropdown.classList.add('open');
      return;
    }

    const highlight = this.getHighlightIds();
    const withExit = highlight.size ? matches.filter(o => highlight.has(o.id)) : [];
    const rest = highlight.size ? matches.filter(o => !highlight.has(o.id)) : matches;

    let html = '';
    if (withExit.length) {
      html += '<div class="prof-picker-group-label">Salidas de sus profesiones</div>';
      html += withExit.map(o => this._optionHtml(o, true)).join('');
      if (rest.length) html += '<div class="prof-picker-group-label">Todas las profesiones</div>';
    }
    html += rest.map(o => this._optionHtml(o, false)).join('');

    this.dropdown.innerHTML = html;
    this.dropdown.classList.add('open');
  }

  _optionHtml(o, isExit) {
    const cls = isExit ? 'prof-picker-option is-exit' : 'prof-picker-option';
    const badge = isExit ? '<span class="prof-picker-exit-badge">&#9733; Salida</span>' : '';
    const safeName = String(o.name).replace(/"/g, '&quot;');
    return `<div class="${cls}" data-id="${o.id}" data-name="${safeName}"><span>${o.name}</span>${badge}</div>`;
  }
}

/**
 * Wire up every not-yet-initialized .prof-picker under rootEl.
 * @param {ParentNode} rootEl
 * @param {{options: Array<{id:number,name:string}>, exitsMap: Object|null}} config
 *   exitsMap: profession_id (string key, per JSON) -> [exit profession ids].
 *   Pass null/undefined to disable exit-highlighting entirely (e.g. for a
 *   character's very first profession, which has no "previous" career).
 */
function initProfessionPickers(rootEl, { options, exitsMap }) {
  rootEl.querySelectorAll('.prof-picker').forEach((root) => {
    if (root.dataset.profPickerInit) return;
    root.dataset.profPickerInit = '1';
    const picker = new ProfessionPicker(root, {
      options,
      getHighlightIds: () => {
        if (!exitsMap) return new Set();
        const set = new Set();
        document.querySelectorAll('.prof-picker-hidden').forEach((inp) => {
          if (inp === picker.hidden || !inp.value) return;
          (exitsMap[inp.value] || []).forEach(id => set.add(id));
        });
        return set;
      },
    });
    root._profPicker = picker;
  });
}
