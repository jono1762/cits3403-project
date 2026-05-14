// Reports listing page scripts:
//   - feed dropdown toggles auto-submit the filter form
//   - star (fav) button on each card toggles via /api/favourites/report
//   - verify / dispute buttons POST to /api/reports/<id>/vote
// All use event delegation so they work regardless of when the cards render.

// Feed dropdown auto-submit: any change inside .listing-feed-toggle submits the form
document.addEventListener('change', (event) => {
    const toggle = event.target.closest('.listing-feed-toggle');
    if (!toggle) return;
    const form = toggle.closest('form');
    if (!form) return;
    form.submit();
});

// Save / unsave a report from the listing card. The button visually toggles
// via the .is-saved class; CSS handles the SVG fill.
document.addEventListener('click', async (event) => {
    const btn = event.target.closest('.listing-fav-btn');
    if (!btn || btn.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    const reportId = btn.dataset.reportId;
    const isSaved = btn.dataset.saved === 'true';
    btn.disabled = true;
    try {
        const method = isSaved ? 'DELETE' : 'POST';
        const res = await csrfFetch(`/api/favourites/report/${reportId}`, { method });
        if (!res.ok) throw new Error('Request failed');
        const nowSaved = !isSaved;
        btn.dataset.saved = nowSaved ? 'true' : 'false';
        btn.classList.toggle('is-saved', nowSaved);
        btn.setAttribute('aria-label', nowSaved ? 'Unsave report' : 'Save report');
        btn.setAttribute('title', nowSaved ? 'Unsave' : 'Save');
    } catch (err) {
        alert('Could not update report favourite.');
    } finally {
        btn.disabled = false;
    }
});

// Verify / dispute vote — auth-only API, guests' buttons are disabled in the
// template so they never reach here. Updates counts + active state inline.
document.addEventListener('click', async (event) => {
    const btn = event.target.closest('.vote-btn');
    if (!btn || btn.disabled) return;
    const bar = btn.closest('.vote-bar');
    if (!bar) return;
    const reportId = bar.dataset.reportId;
    const status = btn.dataset.status;
    try {
        const res = await csrfFetch(`/api/reports/${reportId}/vote`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status}),
        });
        if (!res.ok) return;
        const data = await res.json();
        bar.querySelector('.vote-verify .vote-count').textContent = data.verify_count;
        bar.querySelector('.vote-dispute .vote-count').textContent = data.dispute_count;
        bar.querySelector('.vote-verify').classList.toggle('is-active', data.user_vote === 'verify');
        bar.querySelector('.vote-dispute').classList.toggle('is-active', data.user_vote === 'dispute');
    } catch (err) {
        /* silent fail — keep the UI as-is */
    }
});
