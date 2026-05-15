// ============================================================
// Tab switcher — toggles .is-active + shows/hides panes. Also syncs
// with the URL hash so:
//   - landing on /profile#following activates the Following tab
//     (used after the privacy-toggle form POST redirects with #following)
//   - clicking a tab updates the hash so reload stays on the same tab
// ============================================================
(function () {
    const tabs = document.querySelectorAll('.profile-tab');
    const panes = document.querySelectorAll('.profile-tab-pane');

    function activate(tabName) {
        let matched = false;
        tabs.forEach((btn) => {
            const isMatch = btn.dataset.tab === tabName;
            btn.classList.toggle('is-active', isMatch);
            if (isMatch) matched = true;
        });
        panes.forEach((p) => { p.hidden = p.dataset.pane !== tabName; });
        return matched;
    }

    tabs.forEach((btn) => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            activate(target);
            // update the hash without scrolling, so refresh stays on this tab
            history.replaceState(null, '', '#' + target);
        });
    });

    // on initial load, honour the hash if it points to a known tab
    const initial = (window.location.hash || '').replace('#', '');
    if (initial) activate(initial);
})();

// ============================================================
// Follow / Unfollow AJAX — Instagram-style:
//   • Click "Follow" (when not following) → POST /api/follow/<id> → button flips to "Followed"
//   • Click "Followed" → opens unfollow modal → confirm → DELETE /api/follow/<id> → flips back
// The modal pattern matches the existing delete modals so the UX is consistent.
// ============================================================
(function () {
    const followBtn = document.getElementById('follow-btn');
    if (!followBtn) return;

    const userId = followBtn.dataset.userId;
    const labelEl = followBtn.querySelector('.profile-follow-label');
    const iconEl = document.getElementById('follow-btn-icon');
    const followerCountEl = document.getElementById('profile-follower-count');
    const followingCountEl = document.getElementById('profile-following-count');
    const modalEl = document.getElementById('unfollow-modal');
    const confirmBtn = document.getElementById('unfollow-confirm');

    const ICON_PLUS = 'M12 5v14M5 12h14';      // when not following
    const ICON_CHECK = 'M20 6L9 17l-5-5';      // when followed

    function setState(isFollowing, followerCount, followingCount) {
        followBtn.dataset.following = isFollowing ? 'true' : 'false';
        followBtn.classList.toggle('is-following', isFollowing);
        if (labelEl) labelEl.textContent = isFollowing ? 'Followed' : 'Follow';
        if (iconEl) iconEl.setAttribute('d', isFollowing ? ICON_CHECK : ICON_PLUS);
        if (followerCountEl && typeof followerCount === 'number') {
            followerCountEl.textContent = followerCount;
        }
        if (followingCountEl && typeof followingCount === 'number') {
            followingCountEl.textContent = followingCount;
        }
    }

    followBtn.addEventListener('click', async () => {
        const currentlyFollowing = followBtn.dataset.following === 'true';
        if (currentlyFollowing) {
            // open the unfollow confirmation modal — don't unfollow until user confirms
            if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
            return;
        }
        // not following yet — follow immediately (Instagram-style, no confirm needed)
        followBtn.disabled = true;
        try {
            const res = await csrfFetch(`/api/follow/${userId}`, {method: 'POST'});
            if (res.ok) {
                const data = await res.json();
                setState(data.is_following, data.follower_count, data.following_count);
            }
        } finally {
            followBtn.disabled = false;
        }
    });

    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            confirmBtn.disabled = true;
            try {
                const res = await csrfFetch(`/api/follow/${userId}`, {method: 'DELETE'});
                if (res.ok) {
                    const data = await res.json();
                    setState(data.is_following, data.follower_count, data.following_count);
                }
            } finally {
                confirmBtn.disabled = false;
                if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
            }
        });
    }
})();

// ============================================================
// Save / unsave listing favourite buttons on the profile post grid.
// ============================================================
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
        // SVG stays the same — color fill is driven by CSS via .is-saved
        btn.setAttribute('aria-label', nowSaved ? 'Unsave report' : 'Save report');
        btn.setAttribute('title', nowSaved ? 'Unsave' : 'Save');
    } catch (err) {
        alert('Could not update report favourite.');
    } finally {
        btn.disabled = false;
    }
});

// ============================================================
// Vote (verify/dispute) AJAX — updates the vote-bar AND the live credibility
// stats in the hero (no page reload needed). Server returns author aggregates
// so we can refresh the % + bar fill + verify/dispute breakdown in one go.
// ============================================================
(function () {
    // The id of the user this profile page belongs to — only update the hero
    // credibility when a vote actually changes THIS user's stats.
    const profileStatsRow = document.querySelector('[data-profile-user-id]');
    const profileUserId = profileStatsRow
        ? parseInt(profileStatsRow.dataset.profileUserId, 10)
        : null;

    document.addEventListener('click', async (event) => {
        const btn = event.target.closest('.profile-post-card .vote-btn');
        if (!btn || btn.disabled) return;
        const bar = btn.closest('.vote-bar');
        if (!bar) return;
        const card = btn.closest('.profile-post-card');
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

            // 1) update the vote-bar pills + active state
            bar.querySelector('.vote-verify .vote-count').textContent = data.verify_count;
            bar.querySelector('.vote-dispute .vote-count').textContent = data.dispute_count;
            bar.querySelector('.vote-verify').classList.toggle('is-active', data.user_vote === 'verify');
            bar.querySelector('.vote-dispute').classList.toggle('is-active', data.user_vote === 'dispute');

            // 2) update the "✓ N verified" stat in the same card's footer
            if (card) {
                const verifiedStat = card.querySelector('.profile-post-stat-verified');
                if (verifiedStat) verifiedStat.textContent = '✓ ' + data.verify_count + ' verified';
            }

            // 3) update the hero credibility section if this vote belongs to
            //    the profile owner being viewed (otherwise it's stats for someone else)
            if (data.author_id === profileUserId) {
                const num = document.getElementById('profile-credibility-num');
                const fill = document.getElementById('profile-credibility-fill');
                const verifyTotal = document.getElementById('profile-verify-total');
                const disputeTotal = document.getElementById('profile-dispute-total');

                if (num) {
                    num.textContent = (data.author_credibility === null
                        ? '—'
                        : data.author_credibility + '%');
                }
                if (fill) {
                    fill.style.width = (data.author_credibility === null ? 0 : data.author_credibility) + '%';
                }
                if (verifyTotal) verifyTotal.textContent = '✓ ' + data.author_verify_total + ' verified';
                if (disputeTotal) disputeTotal.textContent = '✗ ' + data.author_dispute_total + ' disputed';
            }
        } catch (err) {
            /* silent fail — keep the UI as-is */
        }
    });
})();
