async function saveInline(form, data) {
  const response = await fetch(form.action, {method:'POST', body:data});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || gettext('Nepavyko išsaugoti.'));
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
document.querySelectorAll('.filter-panel').forEach(form => {
  form.addEventListener('submit', () => {
    form.querySelectorAll('input:not([type=hidden]),select').forEach(control => {
      if (!control.value) control.disabled = true;
    });
  });
});
document.querySelectorAll('[data-filter-multiselect]').forEach(control => {
  const summary = control.querySelector('summary');
  const selectedValues = control.querySelector('[data-filter-selected]');
  const updateSelectedValues = () => {
    const checked = [...control.querySelectorAll('input[type=checkbox]:checked')];
    selectedValues.replaceChildren();
    checked.forEach(input => {
      const label = document.createElement('span');
      label.className = 'crm-label ' + (input.dataset.colorClass || '');
      label.textContent = input.dataset.label;
      selectedValues.append(label);
    });
    if (!checked.length) {
      const placeholder = document.createElement('span');
      placeholder.className = 'filter-placeholder';
      placeholder.textContent = gettext('Pasirinkti');
      selectedValues.append(placeholder);
    }
  };
  summary.addEventListener('click', event => {
    event.preventDefault();
    if (event.detail === 0 || matchMedia('(pointer:coarse)').matches) control.open = !control.open;
  });
  summary.addEventListener('dblclick', event => {
    event.preventDefault();
    control.open = !control.open;
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
