// ============================================================
// Delete-report confirmation — only wired if the modal exists
// (rendered only for the author).
// On confirm: DELETE /api/reports/<id> → redirect to the listing on success.
// ============================================================
(function () {
    const btn = document.getElementById('delete-report-confirm');
    if (!btn) return;
    const backLink = document.querySelector('.report-view-back');
    const listingUrl = backLink ? backLink.getAttribute('href') : '/listing';
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
            const res = await csrfFetch(`/api/reports/${btn.dataset.reportId}`, {method: 'DELETE'});
            if (res.ok) {
                window.location.href = listingUrl;
            } else {
                btn.disabled = false;
                alert('Could not delete the report. Please try again.');
            }
        } catch (err) {
            btn.disabled = false;
            alert('Network error — please try again.');
        }
    });
})();

// ============================================================
// Save / unsave (favourite) the report — only present for authed users.
// ============================================================
(function () {
    const btn = document.getElementById('report-fav-btn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
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
})();

// ============================================================
// Comments JS — covers post, delete (modal), and per-comment vote.
// CRITICAL: any user-submitted text we insert into the DOM uses textContent
// (NOT innerHTML), so HTML / <script> in comment bodies stays inert.
// ============================================================
(function () {
    const form = document.getElementById('comment-form');
    const list = document.getElementById('comment-list');
    const empty = document.getElementById('comment-empty');
    const countEl = document.getElementById('comment-count');
    const commentsSection = document.getElementById('comments');
    const reportId = commentsSection ? parseInt(commentsSection.dataset.reportId, 10) : null;

    function updateCount(delta) {
        if (!countEl) return;
        const n = parseInt(countEl.textContent, 10) || 0;
        countEl.textContent = String(n + delta);
    }

    // ---- safe DOM-builder for a freshly-posted comment ----
    function renderComment(c) {
        const li = document.createElement('li');
        li.className = 'comment-item';
        li.dataset.commentId = c.id;

        // author may be null (deleted account) — render as a non-linked span instead
        const avatar = document.createElement(c.author_url ? 'a' : 'span');
        avatar.className = c.author_url ? 'comment-avatar' : 'comment-avatar comment-avatar-deleted';
        if (c.author_url) avatar.href = c.author_url;
        avatar.setAttribute('aria-hidden', 'true');
        if (c.author_avatar_url) {
            const img = document.createElement('img');
            img.src = c.author_avatar_url;
            img.alt = '';
            avatar.appendChild(img);
        } else {
            avatar.textContent = c.author_initial;
        }

        const body = document.createElement('div');
        body.className = 'comment-body';

        const meta = document.createElement('div');
        meta.className = 'comment-meta';
        const author = document.createElement(c.author_url ? 'a' : 'span');
        author.className = c.author_url ? 'comment-author' : 'comment-author deleted-user';
        if (c.author_url) author.href = c.author_url;
        author.textContent = c.author_username;
        const time = document.createElement('span');
        time.className = 'comment-time';
        time.textContent = '· ' + c.created_at;
        meta.appendChild(author);
        meta.appendChild(time);
        body.appendChild(meta);

        if (c.body) {
            const text = document.createElement('p');
            text.className = 'comment-text';
            text.textContent = c.body;  // textContent → XSS-safe
            body.appendChild(text);
        }

        if (c.media && c.media.length) {
            const mediaList = document.createElement('div');
            mediaList.className = 'comment-media-list';
            for (const m of c.media) {
                const el = m.type === 'image' ? document.createElement('img') : document.createElement('video');
                el.className = 'comment-media-item';
                el.src = m.url;
                if (m.type === 'image') {
                    el.alt = m.original_name;
                } else {
                    el.controls = true;
                }
                mediaList.appendChild(el);
            }
            body.appendChild(mediaList);
        }

        // own comments don't get vote buttons (can't vote on yourself)
        if (!c.is_own) {
            const bar = document.createElement('div');
            bar.className = 'comment-vote-bar';
            bar.dataset.commentId = c.id;
            for (const status of ['verify', 'dispute']) {
                const wrap = document.createElement('span');
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'comment-vote-btn comment-vote-' + status;
                btn.dataset.status = status;
                btn.textContent = (status === 'verify' ? '✓ ' : '✗ ');
                const count = document.createElement('span');
                count.className = 'comment-vote-count';
                count.textContent = String(status === 'verify' ? c.verify_count : c.dispute_count);
                btn.appendChild(count);
                wrap.appendChild(btn);
                bar.appendChild(wrap);
            }
            body.appendChild(bar);
        }

        li.appendChild(avatar);
        li.appendChild(body);

        if (c.is_own) {
            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'comment-delete-btn';
            del.dataset.commentId = c.id;
            del.setAttribute('aria-label', 'Delete your comment');
            del.textContent = '×';
            li.appendChild(del);
        }
        return li;
    }

    // ---- form submit (multipart so we can ship files) ----
    if (form) {
        const input = document.getElementById('comment-body');
        const mediaInput = document.getElementById('comment-media');
        const mediaPreview = document.getElementById('comment-media-preview');
        const hint = document.getElementById('comment-form-hint');
        const attachStatus = document.getElementById('comment-attach-status');
        const defaultHint = hint ? hint.textContent : '';

        const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'];
        const MAX_FILE_SIZE = 200 * 1024 * 1024;
        const MAX_FILES = 5;

        let commentAttachedFiles = [];

        function setAttachStatus(text, isError) {
            if (!attachStatus) return;
            attachStatus.textContent = text;
            attachStatus.classList.toggle('is-error', !!isError);
        }

        function syncCommentMediaInput() {
            const dt = new DataTransfer();
            commentAttachedFiles.forEach(f => dt.items.add(f));
            mediaInput.files = dt.files;
        }

        function setCommentAttachCount() {
            if (commentAttachedFiles.length === 0) setAttachStatus('', false);
            else if (commentAttachedFiles.length === 1) setAttachStatus('1 file selected', false);
            else setAttachStatus(commentAttachedFiles.length + ' files selected', false);
        }

        function renderCommentMediaPreview() {
            if (!mediaPreview) return;
            mediaPreview.innerHTML = '';
            commentAttachedFiles.forEach((file, index) => {
                const thumb = document.createElement('div');
                thumb.className = 'attachment-thumb';
                const isVideo = file.type.startsWith('video/');
                const media = document.createElement(isVideo ? 'video' : 'img');
                media.src = URL.createObjectURL(file);
                if (isVideo) media.muted = true;
                else media.alt = file.name;
                thumb.appendChild(media);
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'remove-btn';
                remove.setAttribute('aria-label', 'Remove attachment');
                remove.textContent = '×';
                remove.addEventListener('click', () => {
                    commentAttachedFiles.splice(index, 1);
                    syncCommentMediaInput();
                    setCommentAttachCount();
                    renderCommentMediaPreview();
                });
                thumb.appendChild(remove);
                mediaPreview.appendChild(thumb);
            });
        }

        if (mediaInput && attachStatus) {
            mediaInput.addEventListener('change', () => {
                const picked = mediaInput.files ? Array.from(mediaInput.files) : [];
                if (picked.length === 0) return;
                for (const nf of picked) {
                    const dup = commentAttachedFiles.some(f => f.name === nf.name && f.size === nf.size);
                    if (dup) continue;
                    const ext = (nf.name.split('.').pop() || '').toLowerCase();
                    if (!ALLOWED_EXTS.includes(ext)) {
                        setAttachStatus(`"${nf.name}" is not allowed. Only images (jpg, png, gif, webp) or videos (mp4, webm, mov).`, true);
                        syncCommentMediaInput();
                        renderCommentMediaPreview();
                        return;
                    }
                    if (nf.size > MAX_FILE_SIZE) {
                        setAttachStatus(`"${nf.name}" is too large — max 200 MB.`, true);
                        syncCommentMediaInput();
                        renderCommentMediaPreview();
                        return;
                    }
                    if (commentAttachedFiles.length >= MAX_FILES) {
                        setAttachStatus(`Too many files — max ${MAX_FILES}.`, true);
                        syncCommentMediaInput();
                        renderCommentMediaPreview();
                        return;
                    }
                    commentAttachedFiles.push(nf);
                }
                syncCommentMediaInput();
                setCommentAttachCount();
                renderCommentMediaPreview();
            });
        }

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const bodyVal = input.value.trim();
            const files = mediaInput ? mediaInput.files : [];
            if (!bodyVal && (!files || files.length === 0)) {
                if (hint) hint.textContent = 'Please write something or attach a file.';
                return;
            }

            const fd = new FormData();
            fd.append('body', bodyVal);
            if (files) {
                for (const f of files) fd.append('media', f);
            }

            try {
                const res = await csrfFetch(`/api/reports/${reportId}/comments`, {
                    method: 'POST',
                    body: fd,
                });
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    if (hint) hint.textContent = data.error || 'Could not post comment.';
                    return;
                }
                const c = await res.json();
                list.appendChild(renderComment(c));
                if (empty) empty.style.display = 'none';
                updateCount(+1);
                input.value = '';
                if (mediaInput) mediaInput.value = '';
                commentAttachedFiles = [];
                if (mediaPreview) mediaPreview.innerHTML = '';
                if (attachStatus) attachStatus.textContent = '';
                if (hint) hint.textContent = defaultHint;
            } catch (err) {
                if (hint) hint.textContent = 'Network error — try again.';
            }
        });
    }

    // ---- delete-comment via Bootstrap modal (no native confirm()) ----
    const deleteModalEl = document.getElementById('delete-comment-modal');
    const deleteConfirmBtn = document.getElementById('delete-comment-confirm');
    let pendingCommentId = null;

    document.addEventListener('click', (event) => {
        const btn = event.target.closest('.comment-delete-btn');
        if (!btn) return;
        pendingCommentId = btn.dataset.commentId;
        if (deleteModalEl) {
            bootstrap.Modal.getOrCreateInstance(deleteModalEl).show();
        }
    });

    if (deleteConfirmBtn) {
        deleteConfirmBtn.addEventListener('click', async () => {
            const id = pendingCommentId;
            if (!id) return;
            deleteConfirmBtn.disabled = true;
            try {
                const res = await csrfFetch(`/api/comments/${id}`, {method: 'DELETE'});
                if (res.ok) {
                    const li = list && list.querySelector(`.comment-item[data-comment-id="${id}"]`);
                    if (li) li.remove();
                    updateCount(-1);
                    if (list && list.children.length === 0 && empty) empty.style.display = '';
                }
            } catch (err) {
                /* silent fail — leave the modal up so the user can try again */
            } finally {
                deleteConfirmBtn.disabled = false;
                pendingCommentId = null;
                if (deleteModalEl) bootstrap.Modal.getInstance(deleteModalEl)?.hide();
            }
        });
    }

    // ---- per-comment verify / dispute vote (event delegation) ----
    document.addEventListener('click', async (event) => {
        const btn = event.target.closest('.comment-vote-btn');
        if (!btn || btn.disabled) return;
        const bar = btn.closest('.comment-vote-bar');
        if (!bar) return;
        const commentId = bar.dataset.commentId;
        const status = btn.dataset.status;
        try {
            const res = await csrfFetch(`/api/comments/${commentId}/vote`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({status}),
            });
            if (!res.ok) return;
            const data = await res.json();
            bar.querySelector('.comment-vote-verify .comment-vote-count').textContent = data.verify_count;
            bar.querySelector('.comment-vote-dispute .comment-vote-count').textContent = data.dispute_count;
            bar.querySelector('.comment-vote-verify').classList.toggle('is-active', data.user_vote === 'verify');
            bar.querySelector('.comment-vote-dispute').classList.toggle('is-active', data.user_vote === 'dispute');
        } catch (err) {
            /* silent fail */
        }
    });
})();

// ============================================================
// AJAX handler for the main report verify/dispute vote bar —
// same pattern as reports_listing.html, just one bar to update.
// ============================================================
document.querySelectorAll('.report-view-vote-bar .vote-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
        if (btn.disabled) return;
        const bar = btn.closest('.vote-bar');
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
            /* silent fail */
        }
    });
});
