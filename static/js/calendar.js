// Calendar: click or drag an empty slot to schedule, click an event to edit.
(() => {
  const dialog = document.getElementById('cal-dialog');
  if (!dialog) return;

  const config = JSON.parse(document.getElementById('cal-config').textContent);
  const form = document.getElementById('cal-form');
  const title = document.getElementById('cal-dialog-title');
  const textField = document.getElementById('cal-text');
  const startField = document.getElementById('cal-start');
  const endField = document.getElementById('cal-end');
  const recordField = document.getElementById('cal-record');
  const recordList = document.getElementById('cal-record-list');
  const recordKind = document.getElementById('cal-record-kind');
  const recordId = document.getElementById('cal-record-id');
  const recordInfo = document.getElementById('cal-record-info');
  const phoneCell = document.getElementById('cal-record-phone');
  const addressCell = document.getElementById('cal-record-address');
  const openRecord = document.getElementById('cal-open-record');
  const deleteButton = document.getElementById('cal-delete');
  const MINUTES = 24 * 60;

  const pad = value => String(value).padStart(2, '0');
  const localValue = date =>
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;

  const atMinutes = (isoDate, minutes) => {
    const [year, month, day] = isoDate.split('-').map(Number);
    return new Date(year, month - 1, day, 0, minutes);
  };

  const snap = minutes => Math.max(0, Math.min(MINUTES, Math.round(minutes / config.snap) * config.snap));

  function setRecord({kind, id, label, phone, address, url}) {
    recordKind.value = kind || '';
    recordId.value = id || '';
    recordField.value = label || '';
    const hasRecord = Boolean(kind && id);
    recordInfo.hidden = !hasRecord;
    phoneCell.textContent = phone || '–';
    addressCell.textContent = address || '–';
    openRecord.hidden = !url;
    if (url) openRecord.href = url;
  }

  function open({id, text, start, end, recordData}) {
    form.action = id ? config.updateUrl.replace(/0\/$/, `${id}/`) : config.createUrl;
    title.textContent = id ? gettext('Redaguoti įvykį') : gettext('Naujas įvykis');
    textField.value = text || '';
    startField.value = start || '';
    endField.value = end || '';
    setRecord(recordData || {});
    deleteButton.hidden = !id;
    if (id) deleteButton.formAction = config.deleteUrl.replace(/0\/delete\/$/, `${id}/delete/`);
    recordList.hidden = true;
    dialog.showModal();
    textField.focus();
  }

  function openForRange(isoDate, startMinutes, endMinutes) {
    open({
      start: localValue(atMinutes(isoDate, startMinutes)),
      end: localValue(atMinutes(isoDate, endMinutes)),
    });
  }

  document.querySelector('[data-cal-new]')?.addEventListener('click', () => {
    const now = new Date();
    const startMinutes = snap(now.getHours() * 60 + now.getMinutes());
    const isoDate = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    openForRange(isoDate, startMinutes, startMinutes + config.defaultMinutes);
  });

  document.querySelectorAll('[data-cal-event]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation();
      const data = button.dataset;
      open({
        id: data.id, text: data.text, start: data.start, end: data.end,
        recordData: {
          kind: data.recordKind, id: data.recordId, label: data.recordLabel,
          phone: data.phone, address: data.address, url: data.recordUrl,
        },
      });
    });
  });

  // --- click / drag on an empty slot of the time grid ---
  document.querySelectorAll('.cal-day').forEach(column => {
    let dragging = null;
    const ghost = document.createElement('div');
    ghost.className = 'cal-ghost';
    ghost.hidden = true;
    column.append(ghost);

    const minutesAt = clientY => {
      const rect = column.getBoundingClientRect();
      return snap(((clientY - rect.top) / rect.height) * MINUTES);
    };
    const paint = (from, to) => {
      ghost.hidden = false;
      ghost.style.top = `${(Math.min(from, to) / MINUTES) * 100}%`;
      ghost.style.height = `${(Math.abs(to - from) / MINUTES) * 100}%`;
    };

    column.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target.closest('.cal-event')) return;
      dragging = {from: minutesAt(event.clientY), to: minutesAt(event.clientY)};
      column.setPointerCapture(event.pointerId);
    });
    column.addEventListener('pointermove', event => {
      if (!dragging) return;
      dragging.to = minutesAt(event.clientY);
      paint(dragging.from, dragging.to);
    });
    column.addEventListener('pointerup', event => {
      if (!dragging) return;
      const {from} = dragging;
      const to = minutesAt(event.clientY);
      dragging = null;
      ghost.hidden = true;
      column.releasePointerCapture(event.pointerId);
      const startMinutes = Math.min(from, to);
      const endMinutes = Math.abs(to - from) < config.snap ? startMinutes + config.defaultMinutes : Math.max(from, to);
      openForRange(column.dataset.date, startMinutes, Math.min(endMinutes, MINUTES));
    });
    column.addEventListener('pointercancel', () => { dragging = null; ghost.hidden = true; });
  });

  // --- month view: clicking a day cell schedules at 09:00 ---
  document.querySelectorAll('[data-cal-month-cell]').forEach(cell => {
    cell.addEventListener('click', event => {
      if (event.target.closest('a,button')) return;
      openForRange(cell.dataset.date, 9 * 60, 9 * 60 + config.defaultMinutes);
    });
  });

  // --- contact / company picker ---
  let searchTimer;
  recordField.addEventListener('input', () => {
    recordKind.value = '';
    recordId.value = '';
    recordInfo.hidden = true;
    openRecord.hidden = true;
    clearTimeout(searchTimer);
    const query = recordField.value.trim();
    if (query.length < 2) { recordList.hidden = true; return; }
    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`${recordField.dataset.recordsUrl}?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        recordList.replaceChildren();
        data.results.forEach(item => {
          const option = document.createElement('button');
          option.type = 'button';
          option.className = 'cal-record-option';
          option.innerHTML = '';
          const label = document.createElement('strong');
          label.textContent = item.label;
          const meta = document.createElement('small');
          meta.textContent = [item.sublabel, item.phone].filter(Boolean).join(' · ');
          option.append(label, meta);
          option.addEventListener('click', () => {
            setRecord(item);
            recordList.hidden = true;
          });
          recordList.append(option);
        });
        recordList.hidden = data.results.length === 0;
      } catch { recordList.hidden = true; }
    }, 200);
  });

  dialog.querySelector('[data-cal-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

  // Open the working day rather than midnight.
  const scroller = document.querySelector('[data-cal-scroll]');
  if (scroller) scroller.scrollTop = (scroller.scrollHeight / 24) * 7.5;
})();
