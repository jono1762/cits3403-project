// Base shell scripts — loaded on every page via base.html.
// Combines: stub-link alerts, expiring-soon banner dismiss, live HH:MM:SS
// countdown on report cards, and sidebar section collapse/expand.

// Stub links — sidebar entries for not-yet-built pages just flash an alert.
document.querySelectorAll('.app-stub-link').forEach((link) => {
    link.addEventListener('click', (event) => {
        event.preventDefault();
        alert(link.dataset.stubMessage || 'Stub: page not available yet.');

        const offcanvasElement = document.getElementById('mobileSidebar');
        if (offcanvasElement) {
            const offcanvasInstance = bootstrap.Offcanvas.getOrCreateInstance(offcanvasElement);
            offcanvasInstance.hide();
        }
    });
});

// Expiring-soon banner — dismissable per session. The dismiss key includes
// the current count so a new report becoming urgent re-shows the banner
// even if the user already dismissed an earlier one.
(function () {
    const banner = document.getElementById('expiring-banner');
    const closeBtn = document.getElementById('expiring-banner-close');
    if (!banner || !closeBtn) return;
    const key = 'expiringBannerDismissed:' + (banner.dataset.count || '0');
    try {
        if (sessionStorage.getItem(key) === '1') {
            banner.style.display = 'none';
        }
    } catch (e) { /* sessionStorage blocked — banner just stays visible */ }
    closeBtn.addEventListener('click', () => {
        banner.style.display = 'none';
        try { sessionStorage.setItem(key, '1'); } catch (e) { /* fine */ }
    });
})();

// Live HH:MM:SS countdown on report cards. Server emits the absolute
// expires_at on each .report-expiry pill via data-expires-at; this loop
// formats the remaining time and re-renders every second.
(function () {
    const URGENT_MS = 24 * 60 * 60 * 1000;   // 24 h — flips pill to orange
    function pad(n) { return String(n).padStart(2, '0'); }
    function formatHMS(ms) {
        const totalSec = Math.max(0, Math.floor(ms / 1000));
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        return pad(h) + ':' + pad(m) + ':' + pad(s);
    }
    function tickExpiries() {
        const now = Date.now();
        document.querySelectorAll('.report-expiry[data-expires-at]').forEach((el) => {
            const target = new Date(el.dataset.expiresAt).getTime();
            if (Number.isNaN(target)) return;
            const ms = target - now;
            el.textContent = '⏰ ' + (ms <= 0 ? 'expired' : formatHMS(ms));
            el.classList.toggle('is-urgent', ms > 0 && ms <= URGENT_MS);
        });
    }
    tickExpiries();
    setInterval(tickExpiries, 1000);
})();

// Sidebar section collapse / expand — persisted via localStorage so collapsed
// state survives page reloads. Initial state is applied synchronously in
// sidebar_state.js (loaded in <head>) to avoid flicker on first paint.
(function () {
    const STORAGE_KEY = 'sidebar-collapsed-sections-v2';
    const sections = document.querySelectorAll('.app-sidebar-group');
    const offcanvasElement = document.getElementById('mobileSidebar');
    const offcanvasInstance = (typeof bootstrap !== 'undefined' && offcanvasElement)
        ? bootstrap.Offcanvas.getOrCreateInstance(offcanvasElement)
        : null;

    function loadCollapsedState() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            return [];
        }
    }

    function saveCollapsedState(collapsedSections) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsedSections));
        } catch (e) {
            // localStorage might be unavailable (private mode, etc)
        }
    }

    function sectionClassName(sectionName) {
        return 'sidebar-section-collapsed-' + sectionName;
    }

    function setSectionState(section, isCollapsed) {
        const sectionName = section.getAttribute('data-section');
        const button = section.querySelector('.app-sidebar-group-header');
        section.classList.toggle('collapsed', isCollapsed);
        button.setAttribute('aria-expanded', !isCollapsed ? 'true' : 'false');
        document.documentElement.classList.toggle(sectionClassName(sectionName), isCollapsed);
    }

    function initSidebar() {
        const collapsedSections = loadCollapsedState();

        document.querySelectorAll('.mobile-sidebar-nav .app-sidebar-link').forEach((link) => {
            link.addEventListener('click', () => {
                if (offcanvasInstance) {
                    offcanvasInstance.hide();
                }
            });
        });

        sections.forEach(section => {
            const sectionName = section.getAttribute('data-section');
            const button = section.querySelector('.app-sidebar-group-header');
            setSectionState(section, collapsedSections.includes(sectionName));

            button.addEventListener('click', () => {
                const isCollapsed = !section.classList.contains('collapsed');
                sections.forEach((matchingSection) => {
                    if (matchingSection.getAttribute('data-section') === sectionName) {
                        setSectionState(matchingSection, isCollapsed);
                    }
                });

                const updated = Array.from(new Set(
                    Array.from(sections)
                        .filter(s => s.classList.contains('collapsed'))
                        .map(s => s.getAttribute('data-section'))
                ));
                saveCollapsedState(updated);
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebar);
    } else {
        initSidebar();
    }
})();
