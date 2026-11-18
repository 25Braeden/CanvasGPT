const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname,
    '../accounts/static/accounts/sync-notices.js'), 'utf8');

function browser({ reduced = false, hasNotice = true, hasClose = true } = {}) {
    let nextId = 0;
    const timers = new Map();
    const handlers = {};
    const classes = new Set();
    const close = { hidden: true, addEventListener: (name, fn) => { handlers[`close:${name}`] = fn; } };
    const notice = {
        hidden: false,
        querySelector: () => hasClose ? close : null,
        classList: { add: name => classes.add(name) },
        contains: target => target === close,
        addEventListener: (name, fn) => { handlers[name] = fn; },
    };
    vm.runInNewContext(script, {
        document: {
            documentElement: { classList: { contains: () => reduced } },
            querySelectorAll: selector => {
                assert.equal(selector, '.sync-status.success[data-sync-notice]');
                return hasNotice ? [notice] : [];
            },
        },
        window: {
            setTimeout(fn, delay) { const id = ++nextId; timers.set(id, { fn, delay }); return id; },
            clearTimeout: id => timers.delete(id),
        },
    });
    return { notice, close, handlers, classes, timers,
        run(delay) {
            for (const [id, timer] of [...timers]) {
                if (timer.delay === delay) { timers.delete(id); timer.fn(); }
            }
        },
    };
}

test('success fades after five seconds then becomes hidden', () => {
    const page = browser();
    assert.equal(page.close.hidden, false);
    assert.equal(page.notice.hidden, false);
    page.run(5000);
    assert.equal(page.classes.has('sync-notice-dismissed'), true);
    assert.equal(page.notice.hidden, false);
    page.run(200);
    assert.equal(page.notice.hidden, true);
});

test('close button dismisses early and cancels auto-dismiss', () => {
    const page = browser();
    page.handlers['close:click']();
    assert.equal([...page.timers.values()].some(t => t.delay === 5000), false);
    page.run(200);
    assert.equal(page.notice.hidden, true);
    page.handlers['close:click']();
    assert.equal(page.timers.size, 0);
});

test('reduced motion hides immediately without a fade', () => {
    const page = browser({ reduced: true });
    page.run(5000);
    assert.equal(page.notice.hidden, true);
    assert.equal(page.classes.size, 0);
    assert.equal(page.timers.size, 0);
});

test('hover pauses the timer and leaving restarts it', () => {
    const page = browser();
    page.handlers.mouseenter();
    page.run(5000);
    assert.equal(page.notice.hidden, false);
    assert.equal(page.timers.size, 0);
    page.handlers.mouseleave();
    page.run(5000);
    page.run(200);
    assert.equal(page.notice.hidden, true);
});

test('keyboard focus pauses dismissal until focus leaves', () => {
    const page = browser();
    page.handlers.focusin();
    assert.equal(page.timers.size, 0);
    page.handlers.focusout({ relatedTarget: page.close });
    assert.equal(page.timers.size, 0);
    page.handlers.focusout({ relatedTarget: null });
    page.run(5000);
    page.run(200);
    assert.equal(page.notice.hidden, true);
});

test('leaving hover does not restart the timer while focus remains', () => {
    const page = browser();
    page.handlers.mouseenter();
    page.handlers.focusin();
    page.handlers.mouseleave();
    assert.equal(page.timers.size, 0);
});

test('stale/failed notices are not selected and no timer starts', () => {
    const page = browser({ hasNotice: false });
    assert.equal(page.timers.size, 0);
    assert.equal(page.notice.hidden, false);
});

test('missing close control does not break the page', () => {
    const page = browser({ hasClose: false });
    assert.equal(page.timers.size, 0);
});
