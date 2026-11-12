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
    const click = (href, event = {}, linkOverrides = {}) => {
        const link = { href, target: '', hasAttribute: () => false, ...linkOverrides };
        handlers.click({
            target: { closest: selector => selector === 'a[data-preserve-scroll]' ? link : null },
            button: 0, defaultPrevented: false, ...event,
        });
    };
    return { window, storage, scrolls, submit, click, show: (persisted = false) => handlers.pageshow({ persisted }) };
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

test('suggestion generation restores assignment scroll on the preview response URL', () => {
    const assignment = 'https://canvasgpt.test/assignments/29/';
    const destination = '/assignments/29/suggestions/generate/';
    // Both successful previews and safe failure pages render at the POST URL.
    // Repeated generation must restore from that URL too.
    for (const sourceUrl of [assignment, `https://canvasgpt.test${destination}`]) {
        const source = browser(sourceUrl);
        source.submit({
            action: `https://canvasgpt.test${destination}`,
            dataset: { scrollPage: destination },
        });
        const result = browser(`https://canvasgpt.test${destination}`, source.storage);
        result.show();
        assert.equal(result.scrolls.length, 1);
        assert.equal(result.scrolls[0].top, 850);
        assert.equal(result.scrolls[0].left, 10);
        assert.equal(result.storage.size, 0);
        result.show();
        assert.equal(result.scrolls.length, 1);
    }
});

test('checklist actions from a suggestion preview restore scroll on the assignment', () => {
    for (const action of ['/tasks/1/toggle/', '/tasks/1/delete/',
        '/tasks/1/move/up/', '/tasks/1/move/down/', '/assignments/29/tasks/add/']) {
        const source = browser('https://canvasgpt.test/assignments/29/suggestions/generate/');
        source.submit({
            action: `https://canvasgpt.test${action}`,
            dataset: { scrollPage: '/assignments/29/' },
        });
        const result = browser('https://canvasgpt.test/assignments/29/', source.storage);
        result.show();
        assert.equal(result.scrolls.length, 1);
        assert.equal(result.scrolls[0].top, 850);
        assert.equal(result.storage.size, 0);
    }
});

test('suggestion generation does not leak scroll to another assignment', () => {
    const source = browser('https://canvasgpt.test/assignments/29/');
    const destination = '/assignments/29/suggestions/generate/';
    source.submit({
        action: `https://canvasgpt.test${destination}`,
        dataset: { scrollPage: destination },
    });
    const result = browser('https://canvasgpt.test/assignments/30/', source.storage);
    result.show();
    assert.equal(result.scrolls.length, 0);
    assert.equal(result.storage.size, 0);
});

test('saving review preserves scroll; discard and acceptance keep assignment navigation normal', () => {
    const review = 'https://canvasgpt.test/suggestions/drafts/1/review/';
    const source = browser(review);
    source.submit();
    const saved = browser(review, source.storage);
    saved.show();
    assert.equal(saved.scrolls.length, 1);
    assert.equal(saved.scrolls[0].top, 850);

    for (const action of ['discard', 'accept']) {
        saved.submit({}, {
            submitter: { formAction: `https://canvasgpt.test/suggestions/drafts/1/${action}/` },
        });
        const assignment = browser('https://canvasgpt.test/assignments/29/', saved.storage);
        assignment.show();
        assert.equal(assignment.scrolls.length, 0);
        assert.equal(assignment.storage.size, 0);
    }
});

test('canonical selected-week redirect restores position from a default plan URL', () => {
    const source = browser();
    source.submit({ dataset: { scrollPage: '/planner/plan/?week=2026-03-02' } });
    const result = browser('https://canvasgpt.test/planner/plan/?week=2026-03-02', source.storage);
    result.show();
    assert.equal(result.scrolls.length, 1);
});

test('previous, current and next week links restore scroll at the selected destination', () => {
    for (const week of ['2026-03-02', '2026-03-09', '2026-03-16']) {
        const source = browser('https://canvasgpt.test/planner/plan/?week=2026-03-09');
        const destination = `https://canvasgpt.test/planner/plan/?week=${week}`;
        source.click(destination);
        const result = browser(destination, source.storage);
        result.show();
        assert.equal(result.scrolls.length, 1);
        assert.equal(result.scrolls[0].top, 850);
        assert.equal(result.scrolls[0].left, 10);
        assert.equal(result.storage.size, 0);
    }
});

test('modified clicks and unrelated navigation do not save a scroll position', () => {
    const week = 'https://canvasgpt.test/planner/plan/?week=2026-03-16';
    for (const event of [
        { ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true },
        { button: 1 }, { defaultPrevented: true }, { target: { closest: () => null } },
    ]) {
        const source = browser();
        source.click(week, event);
        assert.equal(source.storage.size, 0);
    }
    for (const destination of ['https://other.test/planner/plan/',
        'https://canvasgpt.test/dashboard/', `${week}#heading`]) {
        const source = browser();
        source.click(destination);
        assert.equal(source.storage.size, 0);
    }
    for (const overrides of [{ target: '_blank' }, { hasAttribute: () => true }]) {
        const source = browser();
        source.click(week, {}, overrides);
        assert.equal(source.storage.size, 0);
    }
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
    assert.doesNotThrow(() => result.click('https://canvasgpt.test/planner/plan/?week=2026-03-16'));
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
