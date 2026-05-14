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

// mirror the (hidden) file input's selection into the visible status span
const mediaInput = document.getElementById('media');
const mediaStatus = document.getElementById('media-status');
if (mediaInput && mediaStatus) {
    const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'];
    const MAX_FILE_SIZE = 200 * 1024 * 1024;
    const MAX_FILES = 5;

    function setMediaStatus(text, isError) {
        mediaStatus.textContent = text;
        mediaStatus.classList.toggle('is-error', !!isError);
    }

    mediaInput.addEventListener('change', () => {
        const files = mediaInput.files ? Array.from(mediaInput.files) : [];
        const n = files.length;
        if (n === 0) { setMediaStatus('', false); return; }
        if (n > MAX_FILES) {
            mediaInput.value = '';
            setMediaStatus(`Too many files — max ${MAX_FILES}.`, true);
            return;
        }
        for (const f of files) {
            const ext = (f.name.split('.').pop() || '').toLowerCase();
            if (!ALLOWED_EXTS.includes(ext)) {
                mediaInput.value = '';
                setMediaStatus(`"${f.name}" is not allowed. Only images (jpg, png, gif, webp) or videos (mp4, webm, mov).`, true);
                return;
            }
            if (f.size > MAX_FILE_SIZE) {
                mediaInput.value = '';
                setMediaStatus(`"${f.name}" is too large — max 200 MB.`, true);
                return;
            }
        }
        setMediaStatus(n === 1 ? '1 file selected' : n + ' files selected', false);
    });
}
