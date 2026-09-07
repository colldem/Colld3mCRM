async function saveInline(form, data) {
  const response = await fetch(form.action, {method:'POST', body:data});
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || gettext('Nepavyko išsaugoti.'));
    error.payload = result;
    throw error;
  }
  return result;
}
document.querySelectorAll('[popovertarget]').forEach(button => {
  button.addEventListener('click', () => {
    const panel = document.getElementById(button.getAttribute('popovertarget'));
    requestAnimationFrame(() => {
      if (!panel.matches(':popover-open')) return;
      const rect = button.getBoundingClientRect();
      panel.style.margin = '0';
      panel.style.left = Math.max(12, Math.min(rect.left, innerWidth - panel.offsetWidth - 12)) + 'px';
      panel.style.top = Math.max(12, Math.min(rect.bottom + 4, innerHeight - panel.offsetHeight - 12)) + 'px';
    });
  });
});
document.querySelectorAll('[data-close-filter]').forEach(button => {
  button.addEventListener('click', () => button.closest('details')?.removeAttribute('open'));
});
document.addEventListener('pointerdown', event => {
  document.querySelectorAll('.drawer-control[open],.sort-control[open],.filter-multiselect[open],.reminder-menu[open],.profile-menu[open]').forEach(control => {
    if (event.target === control || !control.contains(event.target)) control.removeAttribute('open');
  });
});
document.querySelectorAll('.filter-panel').forEach(form => {
  form.addEventListener('submit', () => {
    form.querySelectorAll('input:not([type=hidden]),select').forEach(control => {
      if (!control.value) control.disabled = true;
    });
  });
});
document.querySelectorAll('[data-filter-multiselect]').forEach(control => {
  const selectedValues = control.querySelector('[data-filter-selected]');
  const updateSelectedValues = () => {
    const checked = [...control.querySelectorAll('input[type=checkbox]:checked')];
    selectedValues.replaceChildren();
    checked.forEach(input => {
      const tag = document.createElement('button');
      tag.type = 'button';
      tag.className = 'filter-selected-tag crm-label ' + (input.dataset.colorClass || '');
      tag.dataset.filterRemove = input.value;
      tag.setAttribute('aria-label', `${gettext('Pašalinti')} ${input.dataset.label}`);
      const label = document.createElement('span');
      label.textContent = input.dataset.label;
      const remove = document.createElement('b');
      remove.setAttribute('aria-hidden', 'true');
      remove.textContent = '×';
      tag.append(label, remove);
      selectedValues.append(tag);
    });
    if (!checked.length) {
      const placeholder = document.createElement('span');
      placeholder.className = 'filter-placeholder';
      placeholder.textContent = gettext('Pasirinkti');
      selectedValues.append(placeholder);
    }
  };
  selectedValues.addEventListener('click', event => {
    const tag = event.target.closest('[data-filter-remove]');
    if (!tag) return;
    event.preventDefault();
    event.stopPropagation();
    const input = [...control.querySelectorAll('input[type=checkbox]')].find(item => item.value === tag.dataset.filterRemove);
    if (!input) return;
    input.checked = false;
    input.dispatchEvent(new Event('change', {bubbles:true}));
  });
  control.addEventListener('change', updateSelectedValues);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelectorAll('.filter-drawer[open]').forEach(drawer => drawer.removeAttribute('open'));
});
document.querySelectorAll('.inline-choices').forEach(form => {
  form.addEventListener('change', async event => {
    const input = event.target;
    const status = form.querySelector('[role=status]');
    const data = new FormData(form);
    const inputs = [...form.querySelectorAll('[type=checkbox]')];
    inputs.forEach(item => item.disabled = true);
    status.textContent = gettext('Saugoma...');
    try {
      await saveInline(form, data);
      const trigger = document.querySelector(`[popovertarget="${form.parentElement.id}"]`);
      trigger.replaceChildren();
      const selected = inputs.filter(item => item.checked);
      selected.forEach(item => { const label = document.createElement('span'); label.className = 'crm-label ' + (item.dataset.colorClass || ''); label.textContent = item.parentElement.textContent.trim(); trigger.append(label); });
      if (!selected.length) trigger.textContent = gettext('Priskirti');
      status.textContent = gettext('Išsaugota');
    } catch (error) { input.checked = !input.checked; status.textContent = error.message; }
    finally { inputs.forEach(item => item.disabled = false); }
  });
});
document.querySelectorAll('.favourite-form').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    const data = new FormData(form);
    data.set('value', button.getAttribute('aria-pressed') !== 'true' ? 'true' : 'false');
    button.disabled = true;
    try { const result = await saveInline(form, data); button.setAttribute('aria-pressed', String(result.value)); button.textContent = result.value ? '★' : '☆'; }
    catch (error) { window.alert(error.message); }
    finally { button.disabled = false; }
  });
});
document.querySelectorAll('[data-edit-url]').forEach(section => {
  const edit = () => location.assign(section.dataset.editUrl);
  section.addEventListener('dblclick', event => {
    if (!event.target.closest('a,button,input,select,textarea,form')) edit();
  });
  section.addEventListener('keydown', event => {
    if (event.target === section && event.key === 'Enter') edit();
  });
  section.querySelector('h2')?.addEventListener('click', () => {
    if (matchMedia('(pointer:coarse)').matches) edit();
  });
});
// Row-menu "Copy email" quick action.
document.addEventListener('click', event => {
  const button = event.target.closest('.copy-email');
  if (!button || !navigator.clipboard) return;
  const original = button.textContent;
  navigator.clipboard.writeText(button.dataset.email || '').then(() => {
    button.textContent = gettext('Nukopijuota');
    setTimeout(() => { button.textContent = original; }, 1500);
  }).catch(() => {});
});
