(() => {
  const SIGNATURE = '#-CookieConsentContainer';
  const OVERLAYS = '.modal-backdrop, [class*="overlay"][class*="cookie"], '
    + '[class*="overlay"][class*="consent"], [class*="overlay"][class*="gdpr"]';
  let sheet = null;
  let scheduled = false;
  let pending = [];

  const findSheet = () => {
    for (const candidate of document.styleSheets) {
      try {
        if (candidate.cssRules.length && candidate.cssRules[0].selectorText
            && candidate.cssRules[0].selectorText.includes(SIGNATURE)) {
          return candidate;
        }
      } catch (_) {}
    }
    return null;
  };

  const clean = roots => {
    sheet ||= findSheet();
    if (!sheet) return;
    for (const root of roots) {
      if (!(root instanceof Element)) continue;
      for (const rule of sheet.cssRules) {
        if (!rule.selectorText) continue;
        try {
          if (root.matches(rule.selectorText)) {
            root.remove();
            break;
          }
          root.querySelectorAll(rule.selectorText).forEach(element => element.remove());
        } catch (_) {}
      }
    }
    document.querySelectorAll(OVERLAYS).forEach(element => element.remove());
    if (document.body) document.body.style.overflow = '';
    document.documentElement.style.overflow = '';
  };

  const flush = () => {
    const roots = pending;
    pending = [];
    scheduled = false;
    clean(roots);
  };

  new MutationObserver(mutations => {
    for (const mutation of mutations) pending.push(...mutation.addedNodes);
    if (!scheduled && pending.length) {
      scheduled = true;
      setTimeout(flush, 50);
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
