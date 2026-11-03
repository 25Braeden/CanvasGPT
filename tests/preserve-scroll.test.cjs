const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../accounts/static/accounts/preserve-scroll.js'), 'utf8');
const key = 'canvasgpt:pending-scroll';

function browser(url = 'https://canvasgpt.test/planner/plan/', storage = new Map()) {
    const handlers = {};
    const scrolls = [];
    const window = {
        location: new URL(url), scrollX: 10, scrollY: 850,
        sessionStorage: {
            getItem: k => storage.get(k) ?? null,
            setItem: (k, v) => storage.set(k, v),
            removeItem: k => storage.delete(k),
        },
        addEventListener: (name, fn) => { handlers[name] = fn; },
        requestAnimationFrame: fn => fn(),
        scrollTo: position => scrolls.push(position),
    };
    const document = { addEventListener: (name, fn) => { handlers[name] = fn; } };
    vm.runInNewContext(script, { window, document, URL });
    const submit = (overrides = {}, event = {}) => handlers.submit({
        target: { method: 'post', action: url, target: '', dataset: {}, ...overrides },
        defaultPrevented: false, ...event,
    });
    return { window, storage, scrolls, submit, show: (persisted = false) => handlers.pageshow({ persisted }) };
}

test('all POST actions restore scroll once when returning to the same page', () => {
    for (const action of ['/tasks/1/toggle/', '/tasks/1/delete/', '/tasks/1/move/up/', '/sync/', '/profile/']) {
        const source = browser();
        source.submit({ action: `https://canvasgpt.test${action}` });
        const result = browser(undefined, source.storage);
        result.show();
        assert.equal(result.scrolls.length, 1);
        assert.equal(result.scrolls[0].top, 850);
        assert.equal(result.scrolls[0].left, 10);
        result.show();
        assert.equal(result.scrolls.length, 1);
    }
});

test('canonical selected-week redirect restores position from a default plan URL', () => {
    const source = browser();
    source.submit({ dataset: { scrollPage: '/planner/plan/?week=2026-03-02' } });
    const result = browser('https://canvasgpt.test/planner/plan/?week=2026-03-02', source.storage);
    result.show();
    assert.equal(result.scrolls.length, 1);
});

test('different destinations and different weeks do not inherit scroll', () => {
    for (const destination of ['/accounts/login/', '/planner/plan/?week=2026-03-09']) {
        const source = browser();
        source.submit();
        const result = browser(`https://canvasgpt.test${destination}`, source.storage);
        result.show();
        assert.equal(result.scrolls.length, 0);
        assert.equal(source.storage.size, 0);
    }
});

test('GET forms, canceled submissions, external actions and new tabs are untouched', () => {
    for (const [form, event] of [
        [{ method: 'get' }, {}], [{}, { defaultPrevented: true }],
        [{ action: 'https://other.test/' }, {}], [{ target: '_blank' }, {}],
    ]) {
        const source = browser();
        source.submit(form, event);
        assert.equal(source.storage.size, 0);
    }
});

test('bad, stale and invalid stored positions are safely ignored', () => {
    for (const value of ['not json', JSON.stringify({ page: '/planner/plan/', savedAt: 0, x: 0, y: 5 }),
        JSON.stringify({ page: '/planner/plan/', savedAt: Date.now(), x: null, y: 'bad' })]) {
        const result = browser(undefined, new Map([[key, value]]));
        assert.doesNotThrow(() => result.show());
        assert.equal(result.scrolls.length, 0);
    }
});

test('blocked storage does not break submissions or page loads', () => {
    const result = browser();
    for (const method of ['setItem', 'getItem', 'removeItem']) {
        result.window.sessionStorage[method] = () => { throw new Error('Storage blocked'); };
    }
    assert.doesNotThrow(() => result.submit());
    assert.doesNotThrow(() => result.show());
});

test('back/forward cache and explicit anchors keep native browser behavior', () => {
    const source = browser();
    source.submit();
    source.show(true);
    assert.equal(source.scrolls.length, 0);
    const anchored = browser('https://canvasgpt.test/planner/plan/#session', source.storage);
    anchored.show();
    assert.equal(anchored.scrolls.length, 0);
});
