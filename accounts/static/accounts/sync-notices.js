(() => {
    'use strict';
    const displayTime = 5000;
    const fadeTime = 200;

    document.querySelectorAll('.sync-status.success[data-sync-notice]').forEach(notice => {
        const close = notice.querySelector('[data-dismiss-sync]');
        if (!close) return;
        close.hidden = false;

        let timer;
        let hovered = false;
        let focused = false;
        let dismissed = false;
        const cancel = () => window.clearTimeout(timer);
        const dismiss = () => {
            if (dismissed) return;
            dismissed = true;
            cancel();
            if (document.documentElement.classList.contains('reduced-motion')) {
                notice.hidden = true;
                return;
            }
            notice.classList.add('sync-notice-dismissed');
            window.setTimeout(() => { notice.hidden = true; }, fadeTime);
        };
        const schedule = () => {
            cancel();
            if (!dismissed && !hovered && !focused) {
                timer = window.setTimeout(dismiss, displayTime);
            }
        };

        close.addEventListener('click', dismiss);
        notice.addEventListener('mouseenter', () => { hovered = true; cancel(); });
        notice.addEventListener('mouseleave', () => { hovered = false; schedule(); });
        notice.addEventListener('focusin', () => { focused = true; cancel(); });
        notice.addEventListener('focusout', event => {
            focused = notice.contains(event.relatedTarget);
            schedule();
        });
        schedule();
    });
})();
