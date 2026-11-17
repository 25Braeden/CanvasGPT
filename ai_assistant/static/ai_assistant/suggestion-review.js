(() => {
    const addButton = document.getElementById('add-student-step');
    const formsContainer = document.getElementById('suggestion-forms');
    const totalForms = document.getElementById('id_suggestions-TOTAL_FORMS');
    const emptyForm = document.getElementById('empty-suggestion-form');
    const maxForms = document.getElementById('id_suggestions-MAX_NUM_FORMS');

    if (!addButton || !formsContainer || !totalForms || !emptyForm) {
        return;
    }

    function removeRow(row, deletion) {
        // Keep the indexed row and DELETE field in the POST so Django can
        // validate the original form count and preserve each step's origin.
        deletion.checked = true;
        row.hidden = true;
        // Hidden required fields must not block browser form validation.
        row.querySelectorAll('input, textarea, select').forEach(field => {
            if (field !== deletion) {
                field.disabled = true;
            }
        });
    }

    function prepareRow(row) {
        const deletion = row.querySelector('input[name$="-DELETE"]');
        const removeButton = row.querySelector('[data-remove-step]');
        const fallback = row.querySelector('[data-remove-fallback]');

        if (!deletion || !removeButton || !fallback) {
            return;
        }

        fallback.hidden = true;
        removeButton.hidden = false;
        if (deletion.checked) {
            removeRow(row, deletion);
        }
        removeButton.addEventListener('click', () => {
            removeRow(row, deletion);
            addButton.focus();
        });
    }

    formsContainer.querySelectorAll('.suggestion-row').forEach(prepareRow);

    addButton.addEventListener('click', () => {
        const formNumber = parseInt(totalForms.value, 10);
        if (maxForms && maxForms.value && formNumber >= parseInt(maxForms.value, 10)) {
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.innerHTML = emptyForm.innerHTML.replace(/__prefix__/g, formNumber);
        const row = wrapper.firstElementChild;
        const selected = row.querySelector('input[name$="-selected"]');
        if (selected) {
            selected.checked = true;
        }
        prepareRow(row);
        formsContainer.appendChild(row);
        totalForms.value = formNumber + 1;
        row.querySelector('textarea').focus();
    });
})();
