// Runs synchronously in <head> so collapsed sidebar sections apply BEFORE
// first paint. Without this, the sidebar would briefly render expanded
// then collapse, causing a flicker on every page load.
(function () {
    try {
        const stored = localStorage.getItem('sidebar-collapsed-sections-v2');
        const collapsedSections = stored ? JSON.parse(stored) : [];
        if (!Array.isArray(collapsedSections)) return;

        collapsedSections.forEach((sectionName) => {
            if (/^[a-z0-9_-]+$/i.test(sectionName)) {
                document.documentElement.classList.add('sidebar-section-collapsed-' + sectionName);
            }
        });
    } catch (e) {
        // localStorage might be unavailable (private mode, etc)
    }
})();
