// A full personal code (11 digits) must never travel in a URL: browser
// history and proxy logs keep URLs. Any GET search form (the top bar, the
// contact list) posts such a query to /search/personal-code/ instead — or, if
// it is marked data-code-post, to its own page as "q" — and the suggestions
// below ask for it by POST.
const looksLikePersonalCode = value => /^\d{11}$/.test(value.replace(/\s+/g, ''));
(() => {
  const url = document.body.dataset.codeSearchUrl;
  if (!url) return;
  document.addEventListener('submit', event => {
    const form = event.target;
    const input = form.querySelector('input[name=q]');
    if (form.method.toLowerCase() !== 'get' || !input || !looksLikePersonalCode(input.value)) return;
    event.preventDefault();
    const post = document.createElement('form');
    post.method = 'post';
    const ownPage = 'codePost' in form.dataset;
    post.action = ownPage ? location.pathname : url;
    post.hidden = true;
    for (const [name, value] of [['csrfmiddlewaretoken', document.body.dataset.csrf], [ownPage ? 'q' : 'code', input.value]]) {
      const field = document.createElement('input');
      field.type = 'hidden'; field.name = name; field.value = value;
      post.append(field);
    }
    document.body.append(post);
    post.submit();
  });
})();

// Live grouped suggestions under the global search box.
(() => {
  const form = document.querySelector('.global-search[data-suggest-url]');
  if (!form) return;
  const input = form.querySelector('input[name=q]');
  const panel = form.querySelector('#search-suggest');
  let timer, controller, lastQuery = '';

  const close = () => {
    panel.hidden = true;
    panel.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
  };

  const render = (data) => {
    panel.replaceChildren();
    if (!data.groups.length) {
      const empty = document.createElement('p');
      empty.className = 'search-suggest-empty';
      empty.textContent = gettext('Nieko nerasta.');
      panel.append(empty);
    }
    data.groups.forEach((group) => {
      const section = document.createElement('div');
      section.className = 'search-suggest-group';
      const head = document.createElement('div');
      head.className = 'search-suggest-head';
      head.textContent = `${group.label} (${group.count})`;
      section.append(head);
      group.items.forEach((item) => {
        const link = document.createElement('a');
        link.href = item.url;
        link.className = 'search-suggest-item';
        const main = document.createElement('span');
        main.textContent = item.label;
        link.append(main);
        if (item.sublabel) {
          const sub = document.createElement('small');
          sub.textContent = item.sublabel;
          link.append(sub);
        }
        section.append(link);
      });
      panel.append(section);
    });
    // No "all results" link for a personal code: that link would carry it in its URL.
    if (data.url) {
      const all = document.createElement('a');
      all.href = data.url;
      all.className = 'search-suggest-all';
      all.textContent = gettext('Rodyti visus rezultatus');
      panel.append(all);
    }
    panel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  const fetchSuggestions = async () => {
    const query = input.value.trim();
    if (query.length < 2) { close(); return; }
    if (query === lastQuery) return;
    lastQuery = query;
    controller?.abort();
    controller = new AbortController();
    try {
      const response = looksLikePersonalCode(query)
        ? await fetch(form.dataset.suggestUrl, {
          method: 'POST', signal: controller.signal, headers: {'X-CSRFToken': document.body.dataset.csrf},
          body: new URLSearchParams({q: query})})
        : await fetch(`${form.dataset.suggestUrl}?q=${encodeURIComponent(query)}`, {signal: controller.signal});
      if (!response.ok) return;
      const data = await response.json();
      if (input.value.trim() === data.q) render(data);
    } catch (_) { /* aborted or offline: keep the box quiet */ }
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(fetchSuggestions, 180);
  });
  input.addEventListener('focus', () => { if (panel.childElementCount) panel.hidden = false; });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { close(); }
  });
  document.addEventListener('pointerdown', (event) => {
    if (!form.contains(event.target)) close();
  });
})();
