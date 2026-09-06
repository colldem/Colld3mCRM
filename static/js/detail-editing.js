function bindDetailField(block) {
  const display = block.querySelector('.field-display');
  const form = block.querySelector('.field-editor');
  const status = form.querySelector('[role=status]');
  let linkTimer;
  const open = () => {
    clearTimeout(linkTimer);
    display.hidden = true; form.hidden = false;
    form.querySelector('input:not([type=hidden]):not(:disabled),textarea,button')?.focus();
  };
  const cancel = () => {
    form.reset(); form.hidden = true; display.hidden = false; status.textContent = '';
    const newCompany = form.querySelector('.new-company-input');
    if (newCompany) { newCompany.hidden = true; newCompany.querySelector('input').disabled = true; form.querySelector('.add-company').setAttribute('aria-expanded', 'false'); }
    display.focus();
  };
  display.addEventListener('dblclick', event => { event.preventDefault(); open(); });
  // Delay plain link navigation so a second click can open the field editor.
  display.querySelectorAll('a').forEach(link => link.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); clearTimeout(linkTimer);
    if (event.detail > 1) return;
    linkTimer = setTimeout(() => {
      if (link.target === '_blank') window.open(link.href, '_blank', 'noopener,noreferrer');
      else location.assign(link.href);
    }, 400);
  }));
  display.addEventListener('keydown', event => { if (event.target === display && event.key === 'Enter') { event.preventDefault(); open(); } });
  display.addEventListener('click', event => { if (matchMedia('(pointer:coarse)').matches && !event.target.closest('a')) open(); });
  form.querySelector('.cancel-field').addEventListener('click', cancel);
  form.addEventListener('keydown', event => { if (event.key === 'Escape' && !form.dataset.saving) { event.preventDefault(); cancel(); } });
  form.querySelector('.add-company')?.addEventListener('click', event => {
    const container = form.querySelector('.new-company-input');
    container.hidden = false; container.querySelector('input').disabled = false;
    event.currentTarget.setAttribute('aria-expanded', 'true'); container.querySelector('input').focus();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.dataset.saving) return;
    const data = new FormData(form);
    const controls = [...form.querySelectorAll('input,textarea,button')];
    const disabled = controls.map(control => control.disabled);
    form.dataset.saving = 'true'; controls.forEach(control => control.disabled = true);
    status.textContent = gettext('Saugoma...');
    try {
      const result = await saveInline(form, data);
      const template = document.createElement('template'); template.innerHTML = result.html;
      const next = template.content.firstElementChild;
      block.replaceWith(next); bindDetailField(next);
      const title = document.querySelector('[data-contact-name],[data-company-name]');
      if (title) title.textContent = result.name;
      const job = document.querySelector('[data-contact-job]');
      if (job) job.textContent = result.job_title;
      next.querySelector('.field-display').focus();
      document.querySelector('#field-save-status').textContent = gettext('Išsaugota');
    } catch (error) { status.textContent = error.message; }
    finally { delete form.dataset.saving; controls.forEach((control, index) => control.disabled = disabled[index]); }
  });
}
document.querySelectorAll('.detail-field').forEach(bindDetailField);
