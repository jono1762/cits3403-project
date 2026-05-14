// Navbar user-search input — live dropdown results from /api/search-users.
// Auth-only; the navbar template only renders the input + results <ul> for
// authenticated users, so this script gates everything on the input existing.
(function () {
    const input = document.getElementById('app-navbar-search-input');
    if (!input) return;

    const resultsList = document.getElementById('app-navbar-search-results');
    let searchTimer;

    function showResults() {
        resultsList.setAttribute('aria-hidden', 'false');
    }
    function hideResults() {
        resultsList.setAttribute('aria-hidden', 'true');
    }

    function performSearch() {
        clearTimeout(searchTimer);
        const q = input.value.trim();
        if (!q) {
            resultsList.innerHTML = '';
            hideResults();
            return;
        }
        searchTimer = setTimeout(async () => {
            try {
                const res = await csrfFetch('/api/search-users?q=' + encodeURIComponent(q));
                const data = await res.json();
                if (data.length === 0) {
                    resultsList.innerHTML = '<li class="app-navbar-search-empty">No users found.</li>';
                } else {
                    resultsList.innerHTML = data.map(u =>
                        `<li><a href="${u.profile_url}">${u.username}</a></li>`
                    ).join('');
                }
                showResults();
            } catch (err) {
                resultsList.innerHTML = '<li class="app-navbar-search-empty">Search failed.</li>';
                showResults();
            }
        }, 200);
    }

    input.addEventListener('input', performSearch);
    input.addEventListener('focus', () => {
        if (resultsList.innerHTML) showResults();
    });

    // close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            hideResults();
            input.blur();
        }
    });
    // close on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !resultsList.contains(e.target)) {
            hideResults();
        }
    });
})();
