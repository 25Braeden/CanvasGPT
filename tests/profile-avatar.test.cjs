const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname,
    '../accounts/static/accounts/profile-avatar.js'), 'utf8');

function image(complete, naturalWidth) {
    const handlers = {};
    return { complete, naturalWidth, hidden: false, handlers,
        addEventListener: (name, callback) => { handlers[name] = callback; },
    };
}
function run(images) {
    vm.runInNewContext(script, { document: { querySelectorAll: () => images } });
}

test('loaded avatars remain visible', () => {
    const avatar = image(true, 100);
    run([avatar]);
    assert.equal(avatar.hidden, false);
});

test('failed image loads reveal the initial', () => {
    const avatar = image(false, 0);
    run([avatar]);
    assert.equal(avatar.hidden, false);
    avatar.handlers.error();
    assert.equal(avatar.hidden, true);
});

test('cached image failures also reveal the initial', () => {
    const avatar = image(true, 0);
    run([avatar]);
    assert.equal(avatar.hidden, true);
});

test('pages without an avatar image do not fail', () => {
    assert.doesNotThrow(() => run([]));
});
