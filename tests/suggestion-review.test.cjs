const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../ai_assistant/static/ai_assistant/suggestion-review.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../ai_assistant/templates/ai_assistant/suggestion_review.html'), 'utf8');

function element(properties = {}) {
    return {
        hidden: false, disabled: false, checked: false,
        handlers: {},
        addEventListener(name, handler) { this.handlers[name] = handler; },
        click() { this.handlers.click?.(); },
        focus() { this.focused = true; },
        ...properties,
    };
}

function makeRow(index, deleted = false) {
    const fields = {
        selected: element({ name: `suggestions-${index}-selected` }),
        description: element({ name: `suggestions-${index}-description`, required: true }),
        estimate: element({ name: `suggestions-${index}-estimated_minutes`, required: true }),
        deletion: element({ name: `suggestions-${index}-DELETE`, checked: deleted }),
    };
    const remove = element({ hidden: true });
    const fallback = element();
    return element({
        fields, remove, fallback,
        querySelector(selector) {
            return {
                'input[name$="-selected"]': fields.selected,
                'input[name$="-DELETE"]': fields.deletion,
                '[data-remove-step]': remove,
                '[data-remove-fallback]': fallback,
                textarea: fields.description,
            }[selector];
        },
        querySelectorAll() { return Object.values(fields); },
    });
}

function browser({ count = 2, max = 20, deleted = [] } = {}) {
    const rows = Array.from({ length: count }, (_, index) => makeRow(index, deleted.includes(index)));
    const add = element();
    const total = { value: String(count) };
    const initial = { value: String(count) };
    const container = {
        querySelectorAll: () => rows,
        appendChild(row) { rows.push(row); },
    };
    // Read the actual empty-form markup rather than hardcoding its placeholder.
    const emptyMarkup = template.match(/<template id="empty-suggestion-form">([\s\S]*?)<\/template>/)[1];
    const elements = {
        'add-student-step': add,
        'suggestion-forms': container,
        'id_suggestions-TOTAL_FORMS': total,
        'id_suggestions-INITIAL_FORMS': initial,
        'id_suggestions-MAX_NUM_FORMS': { value: String(max) },
        'empty-suggestion-form': { innerHTML: emptyMarkup },
    };
    const rendered = [];
    const document = {
        getElementById: id => elements[id],
        createElement() {
            return {
                set innerHTML(html) {
                    rendered.push(html);
                    assert.doesNotMatch(html, /__prefix__/);
                    const index = html.match(/id_suggestions-(\d+)-/)[1];
                    this.firstElementChild = makeRow(index);
                },
            };
        },
    };
    // Django renders these template expressions to indexed names/IDs in the browser.
    elements['empty-suggestion-form'].innerHTML = emptyMarkup.replace(
        /{{ formset\.empty_form\.[^}]+ }}/g,
        '<input id="id_suggestions-__prefix__-field">'
    );
    vm.runInNewContext(script, { document });
    return { rows, add, total, initial, rendered };
}

test('review template loads the tested script and exposes non-submit removal buttons', () => {
    assert.match(template, /static 'ai_assistant\/suggestion-review\.js'/);
    assert.equal((template.match(/type="button" data-remove-step hidden/g) || []).length, 2);
    assert.match(template, /{{ form.DELETE }}/);
    assert.match(template, /{{ formset.empty_form.DELETE }}/);
});

test('adding student steps creates unique indexed rows selected for acceptance', () => {
    const page = browser();
    page.add.click();
    page.add.click();
    assert.equal(page.rows.length, 4);
    assert.equal(Number(page.total.value), 4);
    assert.equal(page.initial.value, '2');
    assert.equal(page.rendered.length, 2);
    for (const index of [2, 3]) {
        const row = page.rows[index];
        assert.equal(row.fields.description.name, `suggestions-${index}-description`);
        assert.equal(row.fields.selected.checked, true);
        assert.equal(row.fields.description.focused, true);
        assert.equal(row.remove.hidden, false);
        assert.equal(row.fallback.hidden, true);
    }
});

test('student steps cannot exceed the formset maximum', () => {
    const page = browser({ count: 2, max: 3 });
    page.add.click();
    page.add.click();
    assert.equal(page.rows.length, 3);
    assert.equal(Number(page.total.value), 3);
});

test('Remove immediately hides an existing row while retaining its DELETE submission', () => {
    const page = browser();
    const row = page.rows[0];
    assert.equal(row.fallback.hidden, true);
    assert.equal(row.remove.hidden, false);
    row.remove.click();
    assert.equal(row.hidden, true);
    assert.equal(row.fields.deletion.checked, true);
    assert.equal(row.fields.deletion.disabled, false);
    assert.equal(row.fields.description.disabled, true);
    assert.equal(row.fields.estimate.disabled, true);
    assert.equal(row.fields.selected.disabled, true);
    assert.equal(page.total.value, '2');
    assert.equal(page.initial.value, '2');
    assert.equal(page.rows[1].hidden, false);
    assert.equal(page.add.focused, true);
});

test('new student steps can be removed without reusing indices or blocking required validation', () => {
    const page = browser();
    page.add.click();
    page.rows[2].remove.click();
    assert.equal(page.rows[2].hidden, true);
    assert.equal(page.rows[2].fields.deletion.checked, true);
    assert.equal(page.rows[2].fields.description.disabled, true);
    page.add.click();
    assert.equal(page.rows[3].fields.description.name, 'suggestions-3-description');
    assert.equal(Number(page.total.value), 4);
});

test('deleted rows remain hidden when server validation redisplays the review', () => {
    const page = browser({ deleted: [1] });
    assert.equal(page.rows[1].hidden, true);
    assert.equal(page.rows[1].fields.deletion.checked, true);
    assert.equal(page.rows[1].fields.deletion.disabled, false);
    assert.equal(page.rows[1].fields.description.disabled, true);
    assert.equal(page.rows[0].hidden, false);
});

test('loading the script outside the review page is harmless', () => {
    assert.doesNotThrow(() => vm.runInNewContext(script, {
        document: { getElementById: () => null },
    }));
});
