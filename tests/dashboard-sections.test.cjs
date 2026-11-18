const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname,
    '../accounts/static/accounts/dashboard-sections.js'), 'utf8');

function browser(storage = new Map(), user = '1', blocked = false) {
    const sections = ['due-soon', 'due-later', 'zero-point', 'past-due'].map(name => ({
        dataset: { dashboardSection: name },
        open: name === 'due-soon',
        addEventListener(event, callback) { this[event] = callback; },
    }));
    const dashboard = {
        dataset: { dashboardUser: user },
        querySelectorAll: () => sections,
    };
    const window = { localStorage: {
        getItem(key) {
            if (blocked) throw new Error('Storage blocked');
            return storage.get(key) ?? null;
        },
        setItem(key, value) {
            if (blocked) throw new Error('Storage blocked');
            storage.set(key, value);
        },
    } };
    vm.runInNewContext(script, {
        window, document: { querySelector: () => dashboard },
    });
    return {
        sections,
        toggle(index, open) {
            sections[index].open = open;
            sections[index].toggle();
        },
    };
}

test('due soon defaults open and the other sections default closed', () => {
    assert.deepEqual(browser().sections.map(s => s.open), [true, false, false, false]);
});

test('opening sections survives refresh and navigation', () => {
    const storage = new Map();
    const page = browser(storage);
    page.toggle(1, true);
    page.toggle(2, true);
    page.toggle(3, true);
    assert.deepEqual(browser(storage).sections.map(s => s.open), [true, true, true, true]);
});

test('closed sections are also remembered including due soon', () => {
    const storage = new Map();
    const page = browser(storage);
    page.toggle(0, false);
    page.toggle(1, true);
    page.toggle(1, false);
    assert.deepEqual(browser(storage).sections.map(s => s.open), [false, false, false, false]);
});

test('preferences are separate for each user on the same browser', () => {
    const storage = new Map();
    browser(storage, '1').toggle(1, true);
    assert.equal(browser(storage, '2').sections[1].open, false);
    assert.equal(browser(storage, '1').sections[1].open, true);
});

test('invalid stored values do not override defaults', () => {
    const storage = new Map([
        ['canvasgpt:dashboard-sections:v1:1:due-soon', 'broken'],
        ['canvasgpt:dashboard-sections:v1:1:due-later', 'null'],
    ]);
    assert.deepEqual(browser(storage).sections.map(s => s.open), [true, false, false, false]);
});

test('blocked storage does not break opening or closing sections', () => {
    const page = browser(new Map(), '1', true);
    assert.deepEqual(page.sections.map(s => s.open), [true, false, false, false]);
    assert.doesNotThrow(() => page.toggle(1, true));
    assert.equal(page.sections[1].open, true);
});

test('pages without a dashboard need no storage or event handlers', () => {
    assert.doesNotThrow(() => vm.runInNewContext(script, {
        document: { querySelector: () => null },
    }));
});
