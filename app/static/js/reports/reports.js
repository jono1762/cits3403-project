const CITIES_BY_STATE = JSON.parse(
    document.getElementById('cities-by-state-data').textContent
);
const stateSelect = document.getElementById('state_id');
const citySelect = document.getElementById('city_id');

stateSelect.addEventListener('change', () => {
    const cities = CITIES_BY_STATE[stateSelect.value] || [];

    citySelect.innerHTML = '<option value="" disabled selected>Select a city...</option>';
    for (const city of cities) {
        const opt = document.createElement('option');
        opt.value = city.id;
        opt.textContent = city.name;
        citySelect.appendChild(opt);
    }
    citySelect.disabled = cities.length === 0;
});

const mediaInput = document.getElementById('media');
const mediaStatus = document.getElementById('media-status');
const mediaPreview = document.getElementById('media-preview');
const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'];
const MAX_FILE_SIZE = 200 * 1024 * 1024;
const MAX_FILES = 5;

function setMediaStatus(text, isError) {
    mediaStatus.textContent = text;
    mediaStatus.classList.toggle('is-error', !!isError);
}

function renderMediaPreview() {
    mediaPreview.innerHTML = '';
    const files = mediaInput.files ? Array.from(mediaInput.files) : [];
    files.forEach((file, index) => {
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
        remove.addEventListener('click', () => removeFileAt(index));
        thumb.appendChild(remove);
        mediaPreview.appendChild(thumb);
    });
}

function removeFileAt(index) {
    const dt = new DataTransfer();
    const files = Array.from(mediaInput.files);
    files.forEach((f, i) => { if (i !== index) dt.items.add(f); });
    mediaInput.files = dt.files;
    mediaInput.dispatchEvent(new Event('change'));
}

mediaInput.addEventListener('change', () => {
    const files = mediaInput.files ? Array.from(mediaInput.files) : [];
    const n = files.length;
    if (n === 0) { setMediaStatus('', false); renderMediaPreview(); return; }
    if (n > MAX_FILES) {
        mediaInput.value = '';
        setMediaStatus(`Too many files — max ${MAX_FILES}.`, true);
        renderMediaPreview();
        return;
    }
    for (const f of files) {
        const ext = (f.name.split('.').pop() || '').toLowerCase();
        if (!ALLOWED_EXTS.includes(ext)) {
            mediaInput.value = '';
            setMediaStatus(`"${f.name}" is not allowed. Only images (jpg, png, gif, webp) or videos (mp4, webm, mov).`, true);
            renderMediaPreview();
            return;
        }
        if (f.size > MAX_FILE_SIZE) {
            mediaInput.value = '';
            setMediaStatus(`"${f.name}" is too large — max 200 MB.`, true);
            renderMediaPreview();
            return;
        }
    }
    setMediaStatus(n === 1 ? '1 file selected' : n + ' files selected', false);
    renderMediaPreview();
});

document.getElementById('report-form').addEventListener('submit', async (event) => {
    event.preventDefault();

    // use FormData so we can send both text fields and uploaded files in one request
    const payload = new FormData();
    payload.append('city_id', citySelect.value);
    payload.append('category_id', document.getElementById('category_id').value);
    payload.append('address', document.getElementById('address').value);
    payload.append('description', document.getElementById('description').value);

    for (const file of mediaInput.files) {
        payload.append('media', file);
    }

    const response = await csrfFetch('/api/reports', {
        method: 'POST',
        body: payload,    // browser sets multipart/form-data + boundary automatically
    });

    if (!response.ok) return;

    const data = await response.json();
    const createMore = document.getElementById('create_more').checked;

    if (createMore) {
        // stay on this page — clear the form so the user can post another
        event.target.reset();
        citySelect.selectedIndex = 0;
        mediaStatus.textContent = '';
        mediaPreview.innerHTML = '';
    } else {
        // jump to the single-report page for the report we just created
        window.location.href = data.view_url;
    }
});
