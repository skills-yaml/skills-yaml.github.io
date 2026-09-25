// Copy buttons and catalog filtering (skills and metapackages). The page works without either.

document.addEventListener('click', async (event) => {
  const button = event.target.closest('.copy');
  if (!button) return;
  const text = button.dataset.copy;
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
