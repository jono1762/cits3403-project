(function () {
    const input = document.getElementById('profile-edit-avatar-input');
    const status = document.getElementById('profile-edit-avatar-status');
    const form = document.getElementById('avatar-upload-form');
    const modalEl = document.getElementById('avatar-preview-modal');
    const modalCircleImg = document.getElementById('modal-preview-circle-img');
    const modalSquareImg = document.getElementById('modal-preview-square-img');
    const modalFilename = document.getElementById('modal-preview-filename');
    const cancelBtn = document.getElementById('avatar-modal-cancel');
    const uploadBtn = document.getElementById('avatar-modal-upload');
    if (!input || !form || !modalEl) return;

    const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp'];
    const MAX_FILE_SIZE = 5 * 1024 * 1024;

    let lastObjectUrl = null;
    let uploading = false;  // set true when user clicks Upload so the modal-hidden handler doesn't clear the input mid-submit

    // bootstrap's bundle is loaded at the very bottom of base.html — AFTER
    // this script. So we can't call bootstrap.Modal here at top-level; we
    // grab the instance lazily, inside the event handler that fires later
    // (by which point bootstrap is definitely defined).
    function getModal() {
        return bootstrap.Modal.getOrCreateInstance(modalEl);
    }

    function clearPick() {
        input.value = '';
        status.textContent = '';
        if (lastObjectUrl) {
            URL.revokeObjectURL(lastObjectUrl);
            lastObjectUrl = null;
        }
    }

    function showError(text) {
        input.value = '';
        status.textContent = text;
        status.classList.add('is-error');
    }

    input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        if (!f) return;
        status.classList.remove('is-error');

        const ext = (f.name.split('.').pop() || '').toLowerCase();
        if (!ALLOWED_EXTS.includes(ext)) {
            showError(`"${f.name}" is not allowed. Only JPG, PNG, GIF, or WebP.`);
            return;
        }
        if (f.size > MAX_FILE_SIZE) {
            showError(`"${f.name}" is too large — max 5 MB.`);
            return;
        }

        status.textContent = f.name;

        // build a preview URL for the picked file and show it inside the modal
        if (lastObjectUrl) URL.revokeObjectURL(lastObjectUrl);
        lastObjectUrl = URL.createObjectURL(f);
        modalCircleImg.src = lastObjectUrl;
        modalSquareImg.src = lastObjectUrl;
        modalFilename.textContent = f.name;

        getModal().show();
    });

    // Cancel button (and the close X / Esc / outside-click via data-bs-dismiss)
    // → discard the file selection so a fresh "Choose image" picks up a new one
    cancelBtn.addEventListener('click', clearPick);
    modalEl.addEventListener('hidden.bs.modal', () => {
        // also clear when the modal is dismissed any other way (Esc / X / backdrop)
        // — but NOT when the user clicked Upload (form is mid-submit)
        if (uploading) return;
        if (input.files && input.files.length > 0) {
            clearPick();
        }
    });

    // Upload → submit the form (triggers the real /settings/avatar POST).
    // The page will navigate after the redirect, so we don't need to do
    // anything else after form.submit() — but we set `uploading` first so
    // the modal-hidden handler above doesn't wipe input.files mid-submit.
    uploadBtn.addEventListener('click', () => {
        uploadBtn.disabled = true;
        uploading = true;
        form.submit();
    });

    // Remove-picture modal — confirm button submits the hidden remove form
    const removeConfirm = document.getElementById('avatar-remove-confirm');
    const removeForm = document.getElementById('avatar-remove-form');
    if (removeConfirm && removeForm) {
        removeConfirm.addEventListener('click', () => {
            removeConfirm.disabled = true;
            removeForm.submit();
        });
    }
})();
