(() => {
    'use strict';
    document.querySelectorAll('[data-profile-avatar]').forEach(image => {
        const showInitial = () => { image.hidden = true; };
        image.addEventListener('error', showInitial);
        // Cached failures may finish before the deferred script runs.
        if (image.complete && image.naturalWidth === 0) showInitial();
    });
})();
