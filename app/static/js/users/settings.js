(function () {
    const currentPw = document.getElementById('settings-current-pw');
    const newPw = document.getElementById('settings-new-pw');
    const confirmPw = document.getElementById('settings-confirm-pw');
    const submitBtn = document.getElementById('password-submit');
    const statusEl = document.getElementById('current-pw-status');
    if (!currentPw || !newPw || !confirmPw || !submitBtn || !statusEl) return;

    let timer;
    let lastChecked = '';

    function setLocked(locked) {
        newPw.disabled = locked;
        confirmPw.disabled = locked;
        submitBtn.disabled = locked;
        if (locked) {
            newPw.value = '';
            confirmPw.value = '';
        }
    }

    function setStatus(state, text) {
        // state: 'idle' | 'ok' | 'error' | 'checking'
        statusEl.textContent = text;
        statusEl.className = 'settings-field-hint' +
            (state === 'ok' ? ' settings-hint-ok' :
             state === 'error' ? ' settings-hint-error' : '');
    }

    currentPw.addEventListener('input', () => {
        clearTimeout(timer);
        const val = currentPw.value;
        if (!val) {
            setLocked(true);
            setStatus('idle', '');
            lastChecked = '';
            return;
        }
        setLocked(true);
        setStatus('checking', 'Checking...');
        timer = setTimeout(async () => {
            // skip the round-trip if the user re-typed the same already-checked string
            if (val === lastChecked) return;
            try {
                const res = await csrfFetch('/api/settings/verify-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({current_password: val}),
                });
                const data = await res.json();
                lastChecked = val;
                if (data.ok) {
                    setStatus('ok', '✓ Verified — you can now set a new password');
                    setLocked(false);
                } else {
                    setStatus('error', '✗ Current password is incorrect');
                    setLocked(true);
                }
            } catch (err) {
                setStatus('error', 'Could not verify — try again.');
            }
        }, 400);
    });
})();
