(function () {
    const ROOT = document.getElementById('messages-page');
    const CURRENT_USER_ID = parseInt(ROOT.dataset.currentUserId, 10);

    // -- inbox elements --
    const chatsList = document.getElementById('chats-list');
    const requestsList = document.getElementById('requests-list');
    const chatsEmpty = document.getElementById('chats-empty');
    const requestsEmpty = document.getElementById('requests-empty');
    const chatsCount = document.getElementById('chats-count');
    const requestsCount = document.getElementById('requests-count');
    const tabButtons = document.querySelectorAll('.messages-tab');
    const panes = document.querySelectorAll('.messages-list-wrap');
    const sidebarBadge = document.querySelector('.sidebar-unread-badge');

    // -- thread elements --
    const threadEmpty = document.getElementById('thread-empty');
    const threadActive = document.getElementById('thread-active');
    const threadAvatar = document.getElementById('thread-avatar');
    const threadName = document.getElementById('thread-name');
    const threadStatus = document.getElementById('thread-status');
    const threadBubbles = document.getElementById('thread-bubbles');
    const threadInput = document.getElementById('thread-input');
    const threadComposer = document.getElementById('thread-composer');
    const threadSendBtn = document.getElementById('thread-send-btn');
    const requestBanner = document.getElementById('thread-request-banner');
    const requestNameEl = document.getElementById('thread-request-name');
    const acceptBtn = document.getElementById('thread-accept-btn');
    const blockBtn = document.getElementById('thread-block-btn');
    const blockLabel = document.getElementById('thread-block-label');
    const blockedBanner = document.getElementById('thread-blocked-banner');

    let activeUserId = null;        // which conversation is open
    let lastMessageAt = null;       // ISO timestamp of latest message we've rendered (for polling)
    let inboxPollTimer = null;
    let threadPollTimer = null;

    // ---- helpers ----
    function updateSidebarBadge(total) {
        if (!sidebarBadge) return;
        if (!total || total <= 0) {
            sidebarBadge.hidden = true;
            sidebarBadge.textContent = '';
        } else {
            sidebarBadge.hidden = false;
            sidebarBadge.textContent = total >= 10 ? '9+' : String(total);
        }
    }

    function formatTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        const now = new Date();
        const sameDay = d.toDateString() === now.toDateString();
        if (sameDay) {
            return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        }
        return d.toLocaleDateString([], {day: '2-digit', month: 'short'});
    }

    // ---- inbox rendering ----
    function buildConversationItem(c) {
        const li = document.createElement('li');
        li.className = 'messages-item';
        li.dataset.userId = c.user_id;
        if (c.user_id === activeUserId) li.classList.add('is-active');
        if (c.unread > 0) li.classList.add('has-unread');

        const avatar = document.createElement('div');
        avatar.className = 'messages-item-avatar';
        if (c.avatar_url) {
            const img = document.createElement('img');
            img.src = c.avatar_url;
            img.alt = '';
            avatar.appendChild(img);
        } else {
            avatar.textContent = c.avatar_initial;
        }

        const body = document.createElement('div');
        body.className = 'messages-item-body';

        const top = document.createElement('div');
        top.className = 'messages-item-top';
        const name = document.createElement('span');
        name.className = 'messages-item-name';
        name.textContent = c.username;
        const time = document.createElement('span');
        time.className = 'messages-item-time';
        time.textContent = formatTime(c.last_at);
        top.appendChild(name);
        top.appendChild(time);

        const previewRow = document.createElement('div');
        previewRow.className = 'messages-item-preview-row';
        const preview = document.createElement('span');
        preview.className = 'messages-item-preview';
        const prefix = c.last_sender_is_me ? 'You: ' : '';
        preview.textContent = prefix + (c.last_body || '(no messages yet)');
        previewRow.appendChild(preview);

        if (c.unread > 0) {
            const unreadBadge = document.createElement('span');
            unreadBadge.className = 'messages-item-unread';
            unreadBadge.textContent = c.unread >= 10 ? '9+' : String(c.unread);
            previewRow.appendChild(unreadBadge);
        }

        body.appendChild(top);
        body.appendChild(previewRow);

        li.appendChild(avatar);
        li.appendChild(body);

        li.addEventListener('click', () => openConversation(c));
        return li;
    }

    async function refreshInbox() {
        try {
            const res = await csrfFetch('/api/conversations');
            if (!res.ok) return;
            const data = await res.json();

            chatsList.innerHTML = '';
            requestsList.innerHTML = '';
            data.chats.forEach(c => chatsList.appendChild(buildConversationItem(c)));
            data.requests.forEach(c => requestsList.appendChild(buildConversationItem(c)));

            chatsEmpty.hidden = data.chats.length > 0;
            requestsEmpty.hidden = data.requests.length > 0;

            chatsCount.textContent = data.chats.length;
            requestsCount.textContent = data.requests.length;

            updateSidebarBadge(data.unread_total);
        } catch (err) { /* silent */ }
    }

    // ---- thread rendering ----
    function buildBubble(m) {
        const li = document.createElement('li');
        li.className = 'messages-bubble ' + (m.sender_is_me ? 'is-mine' : 'is-theirs');

        // body text — only render if present (media-only messages have empty body)
        if (m.body) {
            const text = document.createElement('p');
            text.className = 'messages-bubble-text';
            text.textContent = m.body;  // textContent, not innerHTML — XSS-safe
            li.appendChild(text);
        }

        // attached images / videos in a small grid below the body
        if (m.media && m.media.length) {
            const mediaWrap = document.createElement('div');
            mediaWrap.className = 'messages-bubble-media';
            for (const mm of m.media) {
                const el = mm.type === 'image' ? document.createElement('img') : document.createElement('video');
                el.className = 'messages-bubble-media-item';
                el.src = mm.url;
                if (mm.type === 'image') {
                    el.alt = mm.original_name;
                } else {
                    el.controls = true;
                }
                mediaWrap.appendChild(el);
            }
            li.appendChild(mediaWrap);
        }

        const time = document.createElement('span');
        time.className = 'messages-bubble-time';
        time.textContent = formatTime(m.created_at);
        li.appendChild(time);
        return li;
    }

    async function openConversation(c) {
        activeUserId = c.user_id;
        lastMessageAt = null;
        threadEmpty.hidden = true;
        threadActive.hidden = false;
        threadBubbles.innerHTML = '';

        threadAvatar.replaceChildren();
        threadAvatar.href = c.profile_url;
        if (c.avatar_url) {
            const img = document.createElement('img');
            img.src = c.avatar_url;
            img.alt = '';
            threadAvatar.appendChild(img);
        } else {
            threadAvatar.textContent = c.avatar_initial;
        }
        threadName.textContent = c.username;
        threadName.href = c.profile_url;
        threadStatus.textContent = c.is_request ? 'Message request' : '';

        // visually mark this row active in the inbox
        document.querySelectorAll('.messages-item').forEach(el => el.classList.remove('is-active'));
        const activeEl = document.querySelector(`.messages-item[data-user-id="${c.user_id}"]`);
        if (activeEl) activeEl.classList.add('is-active');

        await loadMessages(activeUserId);
        await markRead(activeUserId);
        startThreadPolling();
    }

    function applyBlockState(isBlocked) {
        // updates the block button + composer visibility based on whether
        // the current user has blocked the OTHER user in this thread
        if (blockBtn) {
            blockBtn.dataset.blocked = isBlocked ? 'true' : 'false';
            blockBtn.classList.toggle('is-blocked', isBlocked);
        }
        if (blockLabel) blockLabel.textContent = isBlocked ? 'Unblock' : 'Block';
        if (blockedBanner) blockedBanner.hidden = !isBlocked;
        if (threadComposer) threadComposer.hidden = isBlocked;
    }

    async function loadMessages(userId) {
        try {
            const res = await csrfFetch(`/api/conversations/${userId}/messages`);
            if (!res.ok) return;
            const data = await res.json();

            threadBubbles.innerHTML = '';
            data.messages.forEach(m => threadBubbles.appendChild(buildBubble(m)));
            if (data.messages.length) lastMessageAt = data.messages[data.messages.length - 1].created_at;
            threadBubbles.scrollTop = threadBubbles.scrollHeight;

            // request banner — only when THIS user is the recipient of a still-pending convo
            if (data.is_request) {
                requestBanner.hidden = false;
                requestNameEl.textContent = threadName.textContent;
            } else {
                requestBanner.hidden = true;
            }

            // sync block button + composer visibility with server state
            applyBlockState(!!data.is_blocked);
        } catch (err) { /* silent */ }
    }

    async function pollNewMessages() {
        if (!activeUserId) return;
        try {
            const url = lastMessageAt
                ? `/api/conversations/${activeUserId}/messages?since=${encodeURIComponent(lastMessageAt)}`
                : `/api/conversations/${activeUserId}/messages`;
            const res = await csrfFetch(url);
            if (!res.ok) return;
            const data = await res.json();
            if (data.messages.length) {
                data.messages.forEach(m => threadBubbles.appendChild(buildBubble(m)));
                lastMessageAt = data.messages[data.messages.length - 1].created_at;
                threadBubbles.scrollTop = threadBubbles.scrollHeight;
                // anything new from them needs to be marked read since we're looking at it
                await markRead(activeUserId);
                refreshInbox();
            }
        } catch (err) { /* silent */ }
    }

    async function markRead(userId) {
        try {
            await csrfFetch(`/api/conversations/${userId}/read`, {method: 'POST'});
        } catch (err) { /* silent */ }
    }

    function startThreadPolling() {
        if (threadPollTimer) clearInterval(threadPollTimer);
        threadPollTimer = setInterval(pollNewMessages, 3000);
    }

    // ---- composer ----
    const threadMediaInput = document.getElementById('thread-media');
    const attachStatus = document.getElementById('thread-attach-status');
    const threadMediaPreview = document.getElementById('thread-media-preview');

    // allowed extensions / size mirror the server-side limits in the api blueprint
    const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'];
    const MAX_FILE_SIZE = 200 * 1024 * 1024;
    const MAX_FILES = 5;

    let attachedThreadFiles = [];

    function showAttachStatus(text, isError) {
        attachStatus.hidden = false;
        attachStatus.textContent = text;
        attachStatus.classList.toggle('is-error', !!isError);
    }

    function clearAttachStatus() {
        attachStatus.hidden = true;
        attachStatus.textContent = '';
        attachStatus.classList.remove('is-error');
    }

    function syncThreadMediaInput() {
        const dt = new DataTransfer();
        attachedThreadFiles.forEach(f => dt.items.add(f));
        threadMediaInput.files = dt.files;
    }

    function setAttachCountStatus() {
        if (attachedThreadFiles.length === 0) clearAttachStatus();
        else if (attachedThreadFiles.length === 1) showAttachStatus('1 file attached', false);
        else showAttachStatus(attachedThreadFiles.length + ' files attached', false);
    }

    function renderThreadMediaPreview() {
        if (!threadMediaPreview) return;
        threadMediaPreview.innerHTML = '';
        attachedThreadFiles.forEach((file, index) => {
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
            remove.addEventListener('click', () => removeThreadMediaAt(index));
            thumb.appendChild(remove);
            threadMediaPreview.appendChild(thumb);
        });
    }

    function removeThreadMediaAt(index) {
        attachedThreadFiles.splice(index, 1);
        syncThreadMediaInput();
        setAttachCountStatus();
        renderThreadMediaPreview();
    }

    threadMediaInput.addEventListener('change', () => {
        const picked = threadMediaInput.files ? Array.from(threadMediaInput.files) : [];
        if (picked.length === 0) return;

        for (const nf of picked) {
            const dup = attachedThreadFiles.some(f => f.name === nf.name && f.size === nf.size);
            if (dup) continue;
            const ext = (nf.name.split('.').pop() || '').toLowerCase();
            if (!ALLOWED_EXTS.includes(ext)) {
                showAttachStatus(`"${nf.name}" is not allowed. Only images (jpg, png, gif, webp) or videos (mp4, webm, mov).`, true);
                syncThreadMediaInput();
                renderThreadMediaPreview();
                return;
            }
            if (nf.size > MAX_FILE_SIZE) {
                showAttachStatus(`"${nf.name}" is too large — max 200 MB.`, true);
                syncThreadMediaInput();
                renderThreadMediaPreview();
                return;
            }
            if (attachedThreadFiles.length >= MAX_FILES) {
                showAttachStatus(`Too many files — max ${MAX_FILES}.`, true);
                syncThreadMediaInput();
                renderThreadMediaPreview();
                return;
            }
            attachedThreadFiles.push(nf);
        }
        syncThreadMediaInput();
        setAttachCountStatus();
        renderThreadMediaPreview();
    });

    threadComposer.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = threadInput.value.trim();
        const files = threadMediaInput.files;
        if (!activeUserId) return;
        if (!body && (!files || files.length === 0)) return;

        threadSendBtn.disabled = true;
        try {
            // FormData → multipart so the server can handle text + files in one POST
            const fd = new FormData();
            fd.append('body', body);
            if (files) {
                for (const f of files) fd.append('media', f);
            }
            const res = await csrfFetch(`/api/conversations/${activeUserId}/messages`, {
                method: 'POST',
                body: fd,
            });
            if (res.ok) {
                const m = await res.json();
                threadBubbles.appendChild(buildBubble(m));
                lastMessageAt = m.created_at;
                threadBubbles.scrollTop = threadBubbles.scrollHeight;
                threadInput.value = '';
                threadInput.style.height = 'auto';
                threadMediaInput.value = '';
                attachedThreadFiles = [];
                attachStatus.hidden = true;
                attachStatus.textContent = '';
                if (threadMediaPreview) threadMediaPreview.innerHTML = '';
                requestBanner.hidden = true;  // sending a reply auto-accepts on the server
                refreshInbox();
            }
        } finally {
            threadSendBtn.disabled = false;
            threadInput.focus();
        }
    });

    // auto-grow textarea up to a sensible cap
    threadInput.addEventListener('input', () => {
        threadInput.style.height = 'auto';
        threadInput.style.height = Math.min(threadInput.scrollHeight, 140) + 'px';
    });

    // Enter sends; Shift+Enter inserts a newline
    threadInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            threadComposer.requestSubmit();
        }
    });

    // ---- accept-request ----
    acceptBtn.addEventListener('click', async () => {
        if (!activeUserId) return;
        acceptBtn.disabled = true;
        try {
            const res = await csrfFetch(`/api/conversations/${activeUserId}/accept`, {method: 'POST'});
            if (res.ok) {
                requestBanner.hidden = true;
                threadStatus.textContent = '';
                refreshInbox();
            }
        } finally {
            acceptBtn.disabled = false;
        }
    });

    // ---- blocked-users list modal — fetches /api/blocked-users on open ----
    const openBlockedListBtn = document.getElementById('open-blocked-modal-btn');
    const blockedListModalEl = document.getElementById('blocked-list-modal');
    const blockedListEl = document.getElementById('blocked-list');
    const blockedListEmpty = document.getElementById('blocked-list-empty');

    // pending state shared with the confirm modal — set when the user clicks
    // Unblock on a row in the blocked-users list, consumed when they confirm
    let pendingListUnblock = null;   // { userId, username, li } | null

    async function refreshBlockedList() {
        try {
            const res = await csrfFetch('/api/blocked-users');
            if (!res.ok) return;
            const users = await res.json();
            blockedListEl.replaceChildren();
            if (users.length === 0) {
                blockedListEmpty.hidden = false;
                return;
            }
            blockedListEmpty.hidden = true;
            for (const u of users) {
                const li = document.createElement('li');
                li.className = 'blocked-list-item';
                li.dataset.userId = u.user_id;

                const avatar = document.createElement('a');
                avatar.className = 'blocked-list-avatar';
                avatar.href = u.profile_url;
                avatar.textContent = u.avatar_initial;

                const name = document.createElement('a');
                name.className = 'blocked-list-name';
                name.href = u.profile_url;
                name.textContent = u.username;

                const unblockBtn = document.createElement('button');
                unblockBtn.type = 'button';
                unblockBtn.className = 'blocked-list-unblock';
                unblockBtn.textContent = 'Unblock';
                unblockBtn.addEventListener('click', () => {
                    // route through the shared confirm modal — hide the list,
                    // show the confirm, perform action, then re-open the list
                    pendingListUnblock = { userId: u.user_id, username: u.username, li };
                    blockConfirmTitle.textContent = 'Unblock ' + u.username + '?';
                    blockConfirmBody.textContent =
                        "They'll be able to message you again. Their old messages won't reappear " +
                        "automatically — they'll come back into your inbox the next time someone sends.";
                    blockConfirmBtn.textContent = 'Unblock';
                    // keep the red destructive style — matches other modals
                    blockConfirmBtn.classList.remove('btn-primary');
                    blockConfirmBtn.classList.add('btn-danger');
                    bootstrap.Modal.getInstance(blockedListModalEl)?.hide();
                    bootstrap.Modal.getOrCreateInstance(blockModalEl).show();
                });

                li.appendChild(avatar);
                li.appendChild(name);
                li.appendChild(unblockBtn);
                blockedListEl.appendChild(li);
            }
        } catch (err) { /* silent */ }
    }

    if (openBlockedListBtn && blockedListModalEl) {
        openBlockedListBtn.addEventListener('click', () => {
            refreshBlockedList();
            bootstrap.Modal.getOrCreateInstance(blockedListModalEl).show();
        });
    }

    // ---- block / unblock — opens the confirm modal first, fetch happens on confirm ----
    const blockModalEl = document.getElementById('block-confirm-modal');
    const blockConfirmBtn = document.getElementById('block-confirm-btn');
    const blockConfirmTitle = document.getElementById('block-confirm-title');
    const blockConfirmBody = document.getElementById('block-confirm-body');

    // If the user opened the confirm modal from the blocked-list (pending
    // unblock set) and then dismisses without confirming, take them back to
    // the list rather than dumping them on the empty inbox.
    if (blockModalEl) {
        blockModalEl.addEventListener('hidden.bs.modal', () => {
            if (pendingListUnblock !== null) {
                pendingListUnblock = null;
                bootstrap.Modal.getOrCreateInstance(blockedListModalEl).show();
            }
        });
    }

    if (blockBtn && blockModalEl && blockConfirmBtn) {
        blockBtn.addEventListener('click', () => {
            if (!activeUserId) return;
            const blocked = blockBtn.dataset.blocked === 'true';
            const name = threadName.textContent || 'this user';

            // swap modal text + confirm-button color based on what we're about to do
            // confirm button stays the standard red destructive style for both
            // actions — matches the look of delete-report / delete-comment etc.
            blockConfirmBtn.classList.remove('btn-primary');
            blockConfirmBtn.classList.add('btn-danger');
            if (blocked) {
                blockConfirmTitle.textContent = 'Unblock ' + name + '?';
                blockConfirmBody.textContent =
                    "They'll be able to message you again. Their old messages won't reappear " +
                    "automatically — they'll come back into your inbox the next time someone sends.";
                blockConfirmBtn.textContent = 'Unblock';
            } else {
                blockConfirmTitle.textContent = 'Block ' + name + '?';
                blockConfirmBody.textContent =
                    "They won't be able to message you, and the conversation disappears " +
                    "from your inbox. They can still see your posts and profile — this is chat-only.";
                blockConfirmBtn.textContent = 'Block';
            }
            bootstrap.Modal.getOrCreateInstance(blockModalEl).show();
        });

        blockConfirmBtn.addEventListener('click', async () => {
            blockConfirmBtn.disabled = true;
            try {
                // Case 1: user is unblocking from the blocked-list modal
                if (pendingListUnblock) {
                    const target = pendingListUnblock;
                    const r = await csrfFetch(`/api/block/${target.userId}`, {method: 'DELETE'});
                    if (r.ok) {
                        target.li.remove();
                        if (blockedListEl.children.length === 0) blockedListEmpty.hidden = false;
                        // if this user's thread is currently open, sync its state too
                        if (parseInt(activeUserId, 10) === target.userId) applyBlockState(false);
                        refreshInbox();
                    }
                    pendingListUnblock = null;
                    bootstrap.Modal.getInstance(blockModalEl)?.hide();
                    // re-open the list so the user can keep managing
                    bootstrap.Modal.getOrCreateInstance(blockedListModalEl).show();
                    return;
                }

                // Case 2: user is blocking/unblocking from inside the open thread
                if (!activeUserId) return;
                const blocked = blockBtn.dataset.blocked === 'true';
                const res = await csrfFetch(`/api/block/${activeUserId}`, {
                    method: blocked ? 'DELETE' : 'POST',
                });
                if (res.ok) {
                    const data = await res.json();
                    applyBlockState(!!data.is_blocked);
                    refreshInbox();   // blocking hides the conversation from inbox
                }
                bootstrap.Modal.getInstance(blockModalEl)?.hide();
            } finally {
                blockConfirmBtn.disabled = false;
            }
        });
    }

    // ---- tab switching ----
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => {
                b.classList.toggle('is-active', b === btn);
                b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
            });
            const target = btn.dataset.tab;
            panes.forEach(p => p.hidden = p.dataset.pane !== target);
        });
    });

    // ---- user search (Instagram-style: type to find someone to chat with) ----
    const searchInput = document.getElementById('messages-search-input');
    const searchClear = document.getElementById('messages-search-clear');
    const searchList = document.getElementById('search-results-list');
    const searchEmpty = document.getElementById('search-empty');
    const searchPane = document.querySelector('.messages-list-wrap[data-pane="search"]');
    const tabsRow = document.querySelector('.messages-tabs');
    const chatsPane = document.querySelector('.messages-list-wrap[data-pane="chats"]');
    const requestsPane = document.querySelector('.messages-list-wrap[data-pane="requests"]');
    let searchTimer;

    function buildSearchResult(u) {
        // shape compatible with openConversation() so clicking just works
        const conv = {
            user_id: u.user_id,
            username: u.username,
            avatar_initial: u.avatar_initial,
            avatar_url: u.avatar_url,
            profile_url: u.profile_url,
            is_request: false,
            unread: 0,
            last_body: '',
            last_at: null,
            last_sender_is_me: false,
        };
        const li = document.createElement('li');
        li.className = 'messages-item';

        const avatar = document.createElement('div');
        avatar.className = 'messages-item-avatar';
        if (u.avatar_url) {
            const img = document.createElement('img');
            img.src = u.avatar_url;
            img.alt = '';
            avatar.appendChild(img);
        } else {
            avatar.textContent = u.avatar_initial;
        }

        const body = document.createElement('div');
        body.className = 'messages-item-body';
        const name = document.createElement('span');
        name.className = 'messages-item-name';
        name.textContent = u.username;
        const sub = document.createElement('span');
        sub.className = 'messages-item-preview';
        sub.textContent = '@' + u.username.toLowerCase() + ' · click to message';
        body.appendChild(name);
        body.appendChild(sub);

        li.appendChild(avatar);
        li.appendChild(body);
        li.addEventListener('click', () => {
            // open the chosen user's thread, then clear search so the inbox
            // returns to view (the new conversation will appear there once a
            // message is sent)
            openConversation(conv);
            searchInput.value = '';
            exitSearchMode();
        });
        return li;
    }

    function enterSearchMode() {
        if (tabsRow) tabsRow.hidden = true;
        if (chatsPane) chatsPane.hidden = true;
        if (requestsPane) requestsPane.hidden = true;
        if (searchPane) searchPane.hidden = false;
        if (searchClear) searchClear.hidden = false;
    }

    function exitSearchMode() {
        if (tabsRow) tabsRow.hidden = false;
        // restore whichever tab was active when the user started searching
        const active = document.querySelector('.messages-tab.is-active');
        const target = active ? active.dataset.tab : 'chats';
        if (chatsPane) chatsPane.hidden = (target !== 'chats');
        if (requestsPane) requestsPane.hidden = (target !== 'requests');
        if (searchPane) searchPane.hidden = true;
        if (searchClear) searchClear.hidden = true;
        searchList.innerHTML = '';
        if (searchEmpty) searchEmpty.hidden = true;
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            const q = searchInput.value.trim();
            if (!q) {
                exitSearchMode();
                return;
            }
            enterSearchMode();
            searchTimer = setTimeout(async () => {
                try {
                    const res = await csrfFetch('/api/search-users?q=' + encodeURIComponent(q));
                    if (!res.ok) return;
                    const users = await res.json();
                    searchList.innerHTML = '';
                    if (users.length === 0) {
                        searchEmpty.hidden = false;
                    } else {
                        searchEmpty.hidden = true;
                        users.forEach(u => searchList.appendChild(buildSearchResult(u)));
                    }
                } catch (err) { /* silent */ }
            }, 200);
        });
    }

    if (searchClear) {
        searchClear.addEventListener('click', () => {
            searchInput.value = '';
            exitSearchMode();
            searchInput.focus();
        });
    }

    // ---- boot + inbox polling ----
    refreshInbox().then(maybeOpenFromQuery);
    inboxPollTimer = setInterval(refreshInbox, 5000);

    // /messages?user=<id> → auto-open that conversation. If the user already
    // exists in the inbox, reuse that data; otherwise fetch a brief user
    // record so we can render the empty thread + composer.
    async function maybeOpenFromQuery() {
        const params = new URLSearchParams(window.location.search);
        const target = parseInt(params.get('user'), 10);
        if (!target || target === CURRENT_USER_ID) return;

        const existing = document.querySelector(`.messages-item[data-user-id="${target}"]`);
        if (existing) { existing.click(); return; }

        // not in the inbox yet — fetch their public profile snippet to build the header
        try {
            const res = await csrfFetch(`/api/users/${target}`);
            if (!res.ok) return;
            const u = await res.json();
            openConversation({
                user_id: u.user_id,
                username: u.username,
                avatar_initial: u.avatar_initial,
                profile_url: u.profile_url,
                is_request: false,
                unread: 0,
                last_body: '',
                last_at: null,
                last_sender_is_me: false,
            });
        } catch (err) { /* silent */ }
    }

    // clean up timers when the user leaves the page
    window.addEventListener('beforeunload', () => {
        if (inboxPollTimer) clearInterval(inboxPollTimer);
        if (threadPollTimer) clearInterval(threadPollTimer);
    });
})();
