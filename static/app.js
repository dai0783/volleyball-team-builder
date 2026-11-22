(() => {
  const menu = document.querySelector('[data-menu]');
  const backdrop = document.querySelector('[data-menu-backdrop]');
  const openButton = document.querySelector('[data-menu-button]');
  const closeButton = document.querySelector('[data-menu-close]');

  function setMenu(open) {
    if (!menu || !backdrop || !openButton) return;
    menu.hidden = !open;
    backdrop.hidden = !open;
    openButton.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('menu-open', open);
  }

  openButton?.addEventListener('click', () => setMenu(true));
  closeButton?.addEventListener('click', () => setMenu(false));
  backdrop?.addEventListener('click', () => setMenu(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMenu(false);
  });

  document.querySelectorAll('[data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.value || target.textContent || '');
        const original = button.textContent;
        button.textContent = 'コピーしました';
        window.setTimeout(() => { button.textContent = original; }, 1400);
      } catch (_error) {
        target.select?.();
        document.execCommand('copy');
      }
    });
  });
})();
