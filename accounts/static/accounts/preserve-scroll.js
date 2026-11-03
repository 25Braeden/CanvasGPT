(() => {
    const key = 'canvasgpt:pending-scroll';
    const maxAge = 5 * 60 * 1000;
    const page = () => window.location.pathname + window.location.search;

    // Delegation covers every form, including checklist controls and future forms.
    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (event.defaultPrevented || form.method.toLowerCase() !== 'post') return;
        const submitter = event.submitter;
        const action = new URL(submitter?.formAction || form.action, window.location.href);
        const target = submitter?.formTarget || form.target;
        if (action.origin !== window.location.origin || (target && target !== '_self')) return;
        try {
            window.sessionStorage.setItem(key, JSON.stringify({
                page: form.dataset.scrollPage || page(),
                x: window.scrollX, y: window.scrollY, savedAt: Date.now(),
            }));
        } catch {
            // Storage may be blocked. Forms must still submit normally.
        }
    });

    window.addEventListener('pageshow', (event) => {
        if (event.persisted) return; // Let the browser restore its back/forward cache.
        try {
            const saved = JSON.parse(window.sessionStorage.getItem(key));
            window.sessionStorage.removeItem(key); // One navigation only; never leak to another page.
            if (!saved || saved.page !== page() || window.location.hash) return;
            const age = Date.now() - saved.savedAt;
            if (!Number.isFinite(age) || age < 0 || age > maxAge) return;
            if (!Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return;
            window.requestAnimationFrame(() => {
                window.scrollTo({ left: saved.x, top: saved.y, behavior: 'instant' });
            });
        } catch {
            // Invalid or unavailable storage must not affect page navigation.
        }
    });
})();
