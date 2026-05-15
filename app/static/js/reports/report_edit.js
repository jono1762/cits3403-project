// cascade: when user changes state, swap the city dropdown contents to match
const CITIES_BY_STATE = JSON.parse(
    document.getElementById('cities-by-state-data').textContent
);
const stateSelect = document.getElementById('state_id');
const citySelect = document.getElementById('city_id');

stateSelect.addEventListener('change', () => {
    const cities = CITIES_BY_STATE[stateSelect.value] || [];
    citySelect.innerHTML = '';
    for (const c of cities) {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name;
        citySelect.appendChild(opt);
    }
});

// clicking the X on a current attachment: tick its hidden checkbox and hide the thumbnail
// the checkbox stays in the form so the server still receives the delete id on submit
document.querySelectorAll('.attachment-thumb .remove-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const thumb = btn.closest('.attachment-thumb');
        thumb.querySelector('input[type="checkbox"]').checked = true;
        thumb.style.display = 'none';
    });
});

const mediaInput = document.getElementById('media');
const mediaStatus = document.getElementById('media-status');
const mediaPreview = document.getElementById('media-preview');
if (mediaInput && mediaStatus) {
    const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'];
    const MAX_FILE_SIZE = 200 * 1024 * 1024;
    const MAX_FILES = 5;

    let editAttachedFiles = [];

    function setMediaStatus(text, isError) {
        mediaStatus.textContent = text;
        mediaStatus.classList.toggle('is-error', !!isError);
    }

    function syncEditMediaInput() {
        const dt = new DataTransfer();
        editAttachedFiles.forEach(f => dt.items.add(f));
        mediaInput.files = dt.files;
    }

    function setEditAttachCount() {
        if (editAttachedFiles.length === 0) setMediaStatus('', false);
        else if (editAttachedFiles.length === 1) setMediaStatus('1 file selected', false);
        else setMediaStatus(editAttachedFiles.length + ' files selected', false);
    }

    function renderEditMediaPreview() {
        if (!mediaPreview) return;
        mediaPreview.innerHTML = '';
        editAttachedFiles.forEach((file, index) => {
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
                editAttachedFiles.splice(index, 1);
                syncEditMediaInput();
                setEditAttachCount();
                renderEditMediaPreview();
            });
            thumb.appendChild(remove);
            mediaPreview.appendChild(thumb);
        });
    }

    mediaInput.addEventListener('change', () => {
        const picked = mediaInput.files ? Array.from(mediaInput.files) : [];
        if (picked.length === 0) return;
        for (const nf of picked) {
            const dup = editAttachedFiles.some(f => f.name === nf.name && f.size === nf.size);
            if (dup) continue;
            const ext = (nf.name.split('.').pop() || '').toLowerCase();
            if (!ALLOWED_EXTS.includes(ext)) {
                setMediaStatus(`"${nf.name}" is not allowed. Only images (jpg, png, gif, webp) or videos (mp4, webm, mov).`, true);
                syncEditMediaInput();
                renderEditMediaPreview();
                return;
            }
            if (nf.size > MAX_FILE_SIZE) {
                setMediaStatus(`"${nf.name}" is too large — max 200 MB.`, true);
                syncEditMediaInput();
                renderEditMediaPreview();
                return;
            }
            if (editAttachedFiles.length >= MAX_FILES) {
                setMediaStatus(`Too many files — max ${MAX_FILES}.`, true);
                syncEditMediaInput();
                renderEditMediaPreview();
                return;
            }
            editAttachedFiles.push(nf);
        }
        syncEditMediaInput();
        setEditAttachCount();
        renderEditMediaPreview();
    });
}
