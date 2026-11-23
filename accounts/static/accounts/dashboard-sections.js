(() => {
    'use strict';

    const dashboard = document.querySelector('[data-dashboard-user]');
    if (!dashboard) return;

    const prefix = `canvasgpt:dashboard-sections:v1:${dashboard.dataset.dashboardUser}:`;
    dashboard.querySelectorAll('details[data-dashboard-section]').forEach(section => {
        const key = prefix + section.dataset.dashboardSection;
        try {
            const saved = window.localStorage.getItem(key);
            if (saved === 'true' || saved === 'false') {
                section.open = saved === 'true';
            }
        } catch {
            // Keep the HTML defaults when storage is unavailable.
        }

        section.addEventListener('toggle', () => {
            try {
                window.localStorage.setItem(key, String(section.open));
            } catch {
                // Sections must still work when storage is blocked or full.
            }
        });
    });
})();
