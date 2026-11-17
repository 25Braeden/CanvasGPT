// Update only the preview; keep the ordinary POST as a no-JavaScript fallback.
(() => {
    const form = document.querySelector('[data-suggestion-generation]');
    const results = document.querySelector('[data-suggestion-results]');
    if (!form || !results || typeof window.fetch !== 'function') return;
    const button = form.querySelector('button[type="submit"]');
    const status = form.querySelector('[data-generation-status]');
    let pending = false;

    form.addEventListener('submit', async (event) => {
        if (event.defaultPrevented) return;
        // Prevent navigation before the shared document-level scroll handler runs.
        event.preventDefault();
        if (pending) return;
        pending = true;
        button.disabled = true;
        form.setAttribute('aria-busy', 'true');
        status.textContent = 'Generating suggestions…';
        try {
            const response = await window.fetch(form.action, {
                method: 'POST',
                body: new FormData(form), // Includes Django's CSRF token.
                credentials: 'same-origin',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
            });
            if (!response.ok || response.redirected) throw new Error('Request failed');
            const data = await response.json();
            if (!data || typeof data.html !== 'string') throw new Error('Invalid response');
            // Only server-rendered Django markup is inserted; suggestion text is escaped there.
            results.innerHTML = data.html;
        } catch {
            const message = document.createElement('p');
            message.setAttribute('role', 'alert');
            message.textContent = 'Could not load suggestions. Try again or add checklist tasks manually.';
            // Do not resubmit automatically: the server may already have audited the attempt.
            results.replaceChildren(message);
        } finally {
            pending = false;
            button.disabled = false;
            form.removeAttribute('aria-busy');
            status.textContent = '';
        }
    });
})();
