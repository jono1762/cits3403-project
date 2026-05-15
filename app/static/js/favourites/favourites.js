// Unstar/remove a saved location from the favourites grid.
document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.fav-panel-star');
    if (!btn) return;
    const panel = btn.closest('.fav-panel');
    const cityId = panel && panel.getAttribute('data-city-id');
    if (!cityId) return;
    if (!confirm('Remove this location from your favourites?')) return;
    csrfFetch(`/api/favourites/location/${cityId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => {
            panel.remove();
            // if no panels left, show empty state
            if (!document.querySelectorAll('.fav-panel').length) {
                const empty = document.createElement('div');
                empty.className = 'fav-empty';
                empty.textContent = 'No saved locations yet. Use the map search to find a place and save it.';
                const grid = document.querySelector('.fav-grid');
                if (grid) grid.replaceWith(empty);
            }
        })
        .catch(() => alert('Could not remove favourite.'));
});
