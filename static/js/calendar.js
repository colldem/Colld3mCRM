// Calendar: click or drag an empty slot to schedule, click an event to edit,
// filter by event type, and lay colleagues' calendars over your own.
(() => {
  const configNode = document.getElementById('cal-config');
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent);
  const MINUTES = 24 * 60;
  const pad = value => String(value).padStart(2, '0');

  // --- the red "now" line: the grid is a 24h column, so the offset is simply
  // how far through the day we are. Kept in step with the clock.
  const nowLine = document.querySelector('[data-cal-now]');
  if (nowLine) {
    const placeNow = () => {
      const now = new Date();
      nowLine.style.top = `${((now.getHours() * 60 + now.getMinutes()) / MINUTES) * 100}%`;
    };
    placeNow();
    setInterval(placeNow, 60000);
  }

  // Open the working day rather than midnight.
  const scroller = document.querySelector('[data-cal-scroll]');
  if (scroller) scroller.scrollTop = (scroller.scrollHeight / 24) * 7.5;

  // ---------------------------------------------------------------- layout --
  // Events sharing an hour sit side by side. The server does this for your own
  // agenda; it has to be redone in the browser whenever a colleague's calendar
  // is switched on or off, or a type filter hides part of the day.
  function layout(column) {
    const items = [...column.querySelectorAll('[data-start-min]')]
      .filter(node => !node.hidden)
      .map(node => ({node, from: Number(node.dataset.startMin), to: Number(node.dataset.endMin)}))
      .sort((a, b) => a.from - b.from || a.to - b.to);
    let cluster = [], clusterEnd = null;
    const flush = () => {
      const lanes = [];
      cluster.forEach(item => {
        let lane = lanes.findIndex(end => end <= item.from);
        if (lane === -1) { lane = lanes.length; }
        lanes[lane] = item.to;
        item.lane = lane;
      });
      const total = Math.max(lanes.length, 1);
      cluster.forEach(item => {
        item.node.style.left = `${(item.lane * 100) / total}%`;
        item.node.style.width = `${100 / total}%`;
      });
      cluster = [];
      clusterEnd = null;
    };
    items.forEach(item => {
      if (cluster.length && item.from >= clusterEnd) flush();
      cluster.push(item);
      clusterEnd = clusterEnd === null ? item.to : Math.max(clusterEnd, item.to);
    });
    if (cluster.length) flush();
  }

  const columns = [...document.querySelectorAll('.cal-day')];
  const relayout = () => columns.forEach(layout);

  // ----------------------------------------------------------- type filter --
  const filter = document.querySelector('[data-cal-filter]');
  if (filter) {
    const hidden = new Set();
    const apply = () => {
      document.querySelectorAll('[data-kind]').forEach(node => {
        if (node.dataset.cal === 'filter-chip') return;
        node.hidden = hidden.has(node.dataset.kind);
      });
      relayout();
    };
    filter.querySelectorAll('.cal-filter-chip').forEach(chip => {
      chip.dataset.cal = 'filter-chip';
      chip.addEventListener('click', () => {
        const kind = chip.dataset.kind;
        const on = hidden.has(kind);
        if (on) hidden.delete(kind); else hidden.add(kind);
        chip.classList.toggle('is-on', on);
        chip.setAttribute('aria-pressed', on ? 'true' : 'false');
        apply();
      });
    });
  }

  // ---------------------------------------------------- colleague calendars --
  const legend = document.querySelector('[data-cal-overlay-legend]');
  const overlayOwners = new Map();

  function refreshLegend() {
    if (!legend) return;
    legend.replaceChildren();
    overlayOwners.forEach(({label, colour}) => {
      const chip = document.createElement('span');
      chip.className = 'cal-legend-chip';
      const dot = document.createElement('i');
      dot.style.background = colour;
      chip.append(dot, document.createTextNode(label));
      legend.append(chip);
    });
    legend.hidden = overlayOwners.size === 0;
  }

  function dropOverlay(id) {
    document.querySelectorAll(`[data-overlay="${id}"]`).forEach(node => node.remove());
    overlayOwners.delete(id);
    refreshLegend();
    relayout();
  }

  function paintOverlay(id, data) {
    const byDate = new Map(columns.map(column => [column.dataset.date, column]));
    data.events.forEach(event => {
      const column = byDate.get(event.date);
      if (!column) return;
      const node = document.createElement('div');
      node.className = `cal-event is-overlay kind-${event.kind}` +
        (event.is_past ? ' is-past' : '') + (event.done ? ' is-done' : '');
      node.dataset.overlay = id;
      node.dataset.kind = event.kind;
      node.dataset.startMin = event.start_min;
      node.dataset.endMin = event.end_min;
      node.style.top = `${(event.start_min / MINUTES) * 100}%`;
      node.style.height = `${((event.end_min - event.start_min) / MINUTES) * 100}%`;
      node.style.setProperty('--overlay-colour', data.colour);
      node.title = `${data.owner}: ${event.label} ${event.text}`;
      const when = document.createElement('b');
      when.textContent = event.label;
      const what = document.createElement('span');
      what.textContent = event.text;
      const who = document.createElement('small');
      who.textContent = data.owner;
      node.append(when, what, who);
      column.append(node);
    });
    overlayOwners.set(id, {label: data.owner, colour: data.colour});
    refreshLegend();
    relayout();
  }

  async function loadOverlay(box) {
    const id = box.dataset.colleague;
    box.disabled = true;
    try {
      const url = config.colleagueUrl.replace(/0\/events\/$/, `${id}/events/`);
      // Never cached: a colleague's agenda is read fresh every time it is shown.
      const response = await fetch(`${url}?view=${config.view}&date=${config.date}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(response.status);
      paintOverlay(id, await response.json());
    } catch {
      box.checked = false;
    } finally {
      box.disabled = false;
    }
  }

  function wireColleague(box) {
    box.addEventListener('change', () => {
      if (box.checked) loadOverlay(box); else dropOverlay(box.dataset.colleague);
    });
  }
  document.querySelectorAll('[data-colleague]').forEach(wireColleague);

  const moreButton = document.querySelector('[data-cal-people-more]');
  if (moreButton) {
    const list = document.getElementById('cal-people-list');
    moreButton.addEventListener('click', async () => {
      moreButton.disabled = true;
      try {
        const offset = Number(moreButton.dataset.offset);
        const response = await fetch(`${moreButton.dataset.url}?offset=${offset}`);
        const data = await response.json();
        data.results.forEach(person => {
          const row = document.createElement('li');
          const label = document.createElement('label');
          label.className = 'cal-person';
          const box = document.createElement('input');
          box.type = 'checkbox';
          box.dataset.colleague = person.id;
          box.dataset.colour = person.colour;
          const dot = document.createElement('i');
          dot.setAttribute('aria-hidden', 'true');
          dot.style.background = person.colour;
          const name = document.createElement('span');
          name.textContent = person.label;
          label.append(box, dot, name);
          row.append(label);
          list.append(row);
          wireColleague(box);
        });
        moreButton.dataset.offset = offset + data.results.length;
        moreButton.hidden = !data.has_more;
      } finally {
        moreButton.disabled = false;
      }
    });
  }

  // -------------------------------------------------------------- the dialog --
  const dialog = document.getElementById('cal-dialog');
  if (!dialog || document.body.dataset.readOnly) return;

  const form = document.getElementById('cal-form');
  const title = document.getElementById('cal-dialog-title');
  const textField = document.getElementById('cal-text');
  const startField = document.getElementById('cal-start');
  const endField = document.getElementById('cal-end');
  const descriptionField = document.getElementById('cal-description');
  const recordField = document.getElementById('cal-record');
  const recordList = document.getElementById('cal-record-list');
  const recordKind = document.getElementById('cal-record-kind');
  const recordId = document.getElementById('cal-record-id');
  const recordInfo = document.getElementById('cal-record-info');
  const partnerCell = document.getElementById('cal-record-partner');
  const phoneCell = document.getElementById('cal-record-phone');
  const addressCell = document.getElementById('cal-record-address');
  const openRecord = document.getElementById('cal-open-record');
  const completeButton = document.getElementById('cal-complete');
  const deleteButton = document.getElementById('cal-delete');
  const repeatField = document.getElementById('cal-repeat-field');
  const notifyBox = document.getElementById('cal-notify');
  const notifyBody = document.getElementById('cal-notify-body');
  const notifySelect = document.getElementById('cal-notify-before');
  const onlineField = document.getElementById('cal-online-field');
  const onlineInput = document.getElementById('cal-meeting-url');
  const onlineLink = document.getElementById('cal-meeting-link');
  const onlineHint = document.getElementById('cal-online-hint');
  const kindInputs = [...form.querySelectorAll('input[name="kind"]')];

  const localValue = date =>
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const atMinutes = (isoDate, minutes) => {
    const [year, month, day] = isoDate.split('-').map(Number);
    return new Date(year, month - 1, day, 0, minutes);
  };
  const snap = minutes => Math.max(0, Math.min(MINUTES, Math.round(minutes / config.snap) * config.snap));
  const currentKind = () => kindInputs.find(input => input.checked)?.value || 'reminder';

  // A meeting shows where it is and how to join; a call or reminder shows the
  // number to ring. The rows only appear once a record is picked.
  function applyKind() {
    const kind = currentKind();
    const meeting = kind === 'meeting';
    onlineField.hidden = !meeting;
    recordInfo.querySelector('[data-record-row="address"]').hidden = !meeting;
    recordInfo.querySelector('[data-record-row="phone"]').hidden = meeting;
    if (!meeting) showOnlineInput();
  }
  kindInputs.forEach(input => input.addEventListener('change', applyKind));

  function showOnlineLink() {
    const value = onlineInput.value.trim();
    if (!value) return showOnlineInput();
    onlineLink.href = value;
    onlineLink.textContent = value;
    onlineLink.hidden = false;
    onlineHint.hidden = false;
    onlineInput.hidden = true;
  }
  function showOnlineInput() {
    onlineLink.hidden = true;
    onlineHint.hidden = true;
    onlineInput.hidden = false;
  }
  onlineInput.addEventListener('blur', showOnlineLink);
  onlineLink.addEventListener('dblclick', event => {
    event.preventDefault();
    showOnlineInput();
    onlineInput.focus();
  });

  notifyBox.addEventListener('change', () => { notifyBody.hidden = !notifyBox.checked; });
  form.querySelectorAll('.cal-quick').forEach(button => {
    button.addEventListener('click', () => {
      notifyBox.checked = true;
      notifyBody.hidden = false;
      notifySelect.value = button.dataset.minutes;
      form.querySelectorAll('.cal-quick').forEach(other => other.classList.toggle('is-on', other === button));
    });
  });

  function setRecord({kind, id, label, phone, address, url, partner}) {
    recordKind.value = kind || '';
    recordId.value = id || '';
    recordField.value = label || '';
    recordInfo.hidden = !(kind && id);
    partnerCell.textContent = partner || '–';
    phoneCell.textContent = phone || '–';
    addressCell.textContent = address || '–';
    openRecord.hidden = !url;
    if (url) openRecord.href = url;
  }

  function open(data) {
    const {id, kind, text, description, start, end, meetingUrl, notifyBefore, done, recordData} = data;
    form.action = id ? config.updateUrl.replace(/0\/$/, `${id}/`) : config.createUrl;
    title.textContent = id ? gettext('Redaguoti įvykį') : gettext('Naujas įvykis');
    kindInputs.forEach(input => { input.checked = input.value === (kind || 'reminder'); });
    textField.value = text || '';
    descriptionField.value = description || '';
    startField.value = start || '';
    endField.value = end || '';
    onlineInput.value = meetingUrl || '';
    notifyBox.checked = Boolean(notifyBefore);
    notifyBody.hidden = !notifyBox.checked;
    notifySelect.value = notifyBefore || '';
    form.querySelectorAll('.cal-quick').forEach(button => button.classList.remove('is-on'));
    setRecord(recordData || {});
    // Recurrence is a property of a new series, not of an occurrence already saved.
    repeatField.hidden = Boolean(id);
    completeButton.hidden = !id || Boolean(done);
    if (id) completeButton.formAction = config.completeUrl.replace(/0\/complete\/$/, `${id}/complete/`);
    deleteButton.hidden = !id;
    if (id) deleteButton.formAction = config.deleteUrl.replace(/0\/delete\/$/, `${id}/delete/`);
    recordList.hidden = true;
    applyKind();
    if (meetingUrl) showOnlineLink();
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
    // Opened from the button rather than the grid: no slot was chosen, so the
    // date is left blank for the user to type.
    open({});
  });

  document.querySelectorAll('[data-cal-event]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation();
      const data = button.dataset;
      open({
        id: data.id, kind: data.kind, text: data.text, description: data.description,
        start: data.start, end: data.end, meetingUrl: data.meetingUrl,
        notifyBefore: data.notifyBefore, done: data.done,
        recordData: {
          kind: data.recordKind, id: data.recordId, label: data.recordLabel,
          phone: data.phone, address: data.address, url: data.recordUrl, partner: data.partner,
        },
      });
    });
  });

  // --- click / drag on an empty slot of the time grid ---
  columns.forEach(column => {
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
          const label = document.createElement('strong');
          label.textContent = item.label;
          const meta = document.createElement('small');
          meta.textContent = [item.sublabel, item.partner, item.phone].filter(Boolean).join(' · ');
          option.append(label, meta);
          option.addEventListener('click', () => {
            setRecord(item);
            applyKind();
            recordList.hidden = true;
          });
          recordList.append(option);
        });
        recordList.hidden = data.results.length === 0;
      } catch { recordList.hidden = true; }
    }, 200);
  });

  dialog.querySelectorAll('[data-cal-close]').forEach(button =>
    button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
})();
