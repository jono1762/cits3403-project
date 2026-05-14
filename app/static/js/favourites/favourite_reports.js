document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.fav-report-card .fav-panel-star');
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    const card = btn.closest('.fav-report-card');
    const reportId = card && card.getAttribute('data-report-id');
    if (!reportId) return;
    if (!confirm('Remove this report from your favourites?')) return;
    csrfFetch(`/api/favourites/report/${reportId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => {
            card.remove();
            if (!document.querySelectorAll('.fav-report-card').length) {
                const empty = document.createElement('div');
                empty.className = 'fav-empty';
                empty.textContent = 'No saved reports yet. Save a report from its report view page.';
                const list = document.querySelector('.fav-report-list');
                if (list) list.replaceWith(empty);
            }
        })
        .catch(() => alert('Could not remove favourite report.'));
});
