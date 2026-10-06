// Copy buttons, catalog filtering (skills and metapackages) and the guide's
// page outline. Each page works without them.

document.addEventListener('click', async (event) => {
  const button = event.target.closest('.copy');
  if (!button) return;
  // A button in a code block's title bar copies the block itself.
  const text = button.dataset.copy ?? button.closest('.code')?.querySelector('pre')?.innerText ?? '';
  const label = button.dataset.label || button.textContent;
  button.dataset.label = label;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Press ⌘C';
  }
  button.dataset.state = 'done';
  setTimeout(() => {
    button.textContent = label;
    delete button.dataset.state;
  }, 1600);
});

const entries = document.getElementById('entries');
if (entries) {
  const input = document.getElementById('q');
  const empty = document.getElementById('empty');
  const cards = [...entries.querySelectorAll('.entry')];
  const groups = [...entries.querySelectorAll('.group')];
  const filters = [...document.querySelectorAll('.filter')];
  let category = 'all';

  const apply = () => {
    const query = input.value.trim().toLowerCase();
    let shown = 0;
    for (const card of cards) {
      const match =
        (category === 'all' || card.dataset.category === category) &&
        (!query || card.dataset.search.includes(query));
      card.hidden = !match;
      if (match) shown += 1;
    }
    for (const group of groups) {
      group.hidden = ![...group.querySelectorAll('.entry')].some((card) => !card.hidden);
    }
    empty.hidden = shown > 0;
  };

  input.addEventListener('input', apply);
  for (const filter of filters) {
    filter.addEventListener('click', () => {
      category = filter.dataset.filter;
      for (const other of filters) {
        other.setAttribute('aria-pressed', String(other === filter));
      }
      apply();
    });
  }
}

// Mark the section being read in the "On this page" outline.
const outline = document.querySelector('.docs-toc');
if (outline && 'IntersectionObserver' in window) {
  const links = new Map(
    [...outline.querySelectorAll('a[href^="#"]')].map((link) => [link.hash.slice(1), link]),
  );
  const visible = new Set();
  const mark = () => {
    const current = [...links.keys()].find((id) => visible.has(id));
    if (!current) return;
    for (const [id, link] of links) {
      if (id === current) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
  };
  const observer = new IntersectionObserver((records) => {
    for (const record of records) {
      if (record.isIntersecting) visible.add(record.target.id);
      else visible.delete(record.target.id);
    }
    mark();
  }, { rootMargin: '-80px 0px -55% 0px' });
  for (const id of links.keys()) {
    const section = document.getElementById(id);
    if (section) observer.observe(section);
  }
}
