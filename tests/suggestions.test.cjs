const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const suggestions = fs.readFileSync(path.join(__dirname, '../ai_assistant/static/ai_assistant/suggestions.js'), 'utf8');
const preserveScroll = fs.readFileSync(path.join(__dirname, '../accounts/static/accounts/preserve-scroll.js'), 'utf8');

function browser(fetchResult = async () => ({ ok: true, redirected: false, json: async () => ({ html: '<p>Preview</p>' }) })) {
    const documentHandlers = {};
    const formHandlers = {};
    const storage = new Map();
    const calls = [];
    const scrolls = [];
    const button = { disabled: false };
    const status = { textContent: '' };
    const results = {
        innerHTML: '<p>Previous preview</p>',
        replaceChildren(child) { this.child = child; this.innerHTML = ''; },
    };
    const form = {
        action: 'https://canvasgpt.test/assignments/29/suggestions/generate/',
        method: 'post', target: '', dataset: { scrollPage: '/assignments/29/suggestions/generate/' },
        attributes: {},
        querySelector: selector => selector === 'button[type="submit"]' ? button : status,
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
        addEventListener(name, callback) { formHandlers[name] = callback; },
    };
    const document = {
        querySelector: selector => selector === '[data-suggestion-generation]' ? form : results,
        addEventListener(name, callback) { documentHandlers[name] = callback; },
        createElement: () => ({ setAttribute(name, value) { this[name] = value; } }),
    };
    const window = {
        location: new URL('https://canvasgpt.test/assignments/29/'), scrollX: 0, scrollY: 850,
        sessionStorage: {
            getItem: key => storage.get(key) ?? null,
            setItem: (key, value) => storage.set(key, value),
            removeItem: key => storage.delete(key),
        },
        addEventListener() {},
        scrollTo: position => scrolls.push(position),
        fetch: fetchResult ? (...args) => { calls.push(args); return fetchResult(...args); } : undefined,
    };
    class FormData {
        constructor(source) { this.source = source; }
    }
    const context = vm.createContext({ window, document, FormData, URL });
    vm.runInContext(suggestions, context);
    vm.runInContext(preserveScroll, context);
    const submit = (canceled = false) => {
        const event = {
            target: form, defaultPrevented: canceled,
            preventDefault() { this.defaultPrevented = true; },
        };
        const done = formHandlers.submit?.(event);
        // Match event bubbling: the shared scroll listener sees cancellation.
        documentHandlers.submit(event);
        return { event, done };
    };
    return { window, form, button, status, results, storage, scrolls, calls, submit };
}

test('suggestions update in place without navigation or a pending scroll restore', async () => {
    const page = browser();
    const { event, done } = page.submit();
    assert.equal(event.defaultPrevented, true);
    assert.equal(page.button.disabled, true);
    assert.equal(page.form.attributes['aria-busy'], 'true');
    assert.match(page.status.textContent, /Generating/);
    await done;
    assert.equal(page.results.innerHTML, '<p>Preview</p>');
    assert.equal(page.window.location.pathname, '/assignments/29/');
    assert.equal(page.window.scrollY, 850);
    assert.equal(page.scrolls.length, 0);
    assert.equal(page.storage.size, 0);
    assert.equal(page.button.disabled, false);
    assert.equal(page.form.attributes['aria-busy'], undefined);
    assert.equal(page.status.textContent, '');
    const [url, options] = page.calls[0];
    assert.equal(url, page.form.action);
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.headers['X-Requested-With'], 'XMLHttpRequest');
    assert.equal(options.headers.Accept, 'application/json');
    assert.equal(options.body.source, page.form);
});

test('duplicate submits are blocked while pending, but generation can be retried', async () => {
    let resolve;
    const pending = new Promise(done => { resolve = done; });
    const page = browser(() => pending);
    const first = page.submit();
    await page.submit().done;
    assert.equal(page.calls.length, 1);
    resolve({ ok: true, redirected: false, json: async () => ({ html: '<p>Done</p>' }) });
    await first.done;
    await page.submit().done;
    assert.equal(page.calls.length, 2);
    assert.equal(page.button.disabled, false);
    assert.equal(page.storage.size, 0);
});

test('safe service failures render inline without reloading', async () => {
    const page = browser(async () => ({
        ok: true, redirected: false,
        json: async () => ({ html: '<p role="alert">Add tasks manually.</p>' }),
    }));
    await page.submit().done;
    assert.match(page.results.innerHTML, /Add tasks manually/);
    assert.equal(page.calls.length, 1);
    assert.equal(page.storage.size, 0);
});

test('network, CSRF, login redirects, and malformed responses show safe retryable errors', async () => {
    for (const result of [
        async () => { throw new Error('Sensitive network error'); },
        async () => ({ ok: false, redirected: false }),
        async () => ({ ok: true, redirected: true }),
        async () => ({ ok: true, json: async () => { throw new Error('Not JSON'); } }),
        async () => ({ ok: true, json: async () => ({ html: null }) }),
        async () => ({ ok: true, json: async () => null }),
    ]) {
        const page = browser(result);
        await page.submit().done;
        assert.equal(page.results.child.role, 'alert');
        assert.match(page.results.child.textContent, /Try again or add checklist tasks manually/);
        assert.doesNotMatch(page.results.child.textContent, /Sensitive/);
        assert.equal(page.button.disabled, false);
        assert.equal(page.status.textContent, '');
        assert.equal(page.calls.length, 1); // No automatic duplicate POST.
        assert.equal(page.storage.size, 0);
    }
});

test('already canceled submissions do not start requests', async () => {
    const page = browser();
    await page.submit(true).done;
    assert.equal(page.calls.length, 0);
    assert.equal(page.storage.size, 0);
});

test('browsers without fetch retain ordinary POST and shared scroll preservation', () => {
    const page = browser(null);
    const { event } = page.submit();
    assert.equal(event.defaultPrevented, false);
    assert.equal(page.button.disabled, false);
    assert.equal(page.storage.size, 1);
    assert.equal(JSON.parse([...page.storage.values()][0]).page, '/assignments/29/suggestions/generate/');
});
