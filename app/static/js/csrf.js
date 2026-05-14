// Drop-in replacement for fetch() that auto-attaches the CSRF token
// to state-changing requests. Use csrfFetch() in templates instead of
// fetch() for any POST / PUT / PATCH / DELETE call. The header is
// harmless on GET requests, so it's fine to use csrfFetch everywhere.
function csrfFetch(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (!opts.headers['X-CSRFToken']) {
        opts.headers['X-CSRFToken'] = document.querySelector('meta[name="csrf-token"]').content;
    }
    return fetch(url, opts);
}
