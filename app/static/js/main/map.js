// Leaflet map page — Australia-bounded view with searchable pins per city.
// Server-injected URLs + flags come from <script type="application/json"
// id="map-config-data"> in the template; we parse it once on load.

const MAP_CONFIG = JSON.parse(document.getElementById('map-config-data').textContent);
const CITY_IDS_BY_NAME = JSON.parse(document.getElementById('city-ids-data').textContent);
const cityData = JSON.parse(document.getElementById('map-cities-data').textContent);

const LIVE_WEATHER_URL = MAP_CONFIG.live_weather_url;
const LISTING_URL = MAP_CONFIG.listing_url;
const IS_GUEST = MAP_CONFIG.is_guest;

const searchBar = document.getElementById('searchBar');
const searchButton = document.getElementById('searchButton');
const suggestions = document.getElementById('suggestions');
const searchWrapper = document.querySelector('.search-wrapper');
const australiaBounds = [[-45.5, 106.0], [-8.0, 160.0]];
const southBound = australiaBounds[0][0];
const westBound = australiaBounds[0][1];
const northBound = australiaBounds[1][0];
const eastBound = australiaBounds[1][1];
const defaultView = { center: [-27.0, 133.7751], zoom: 3.5 };
const map = L.map('map', {
    center: defaultView.center,
    zoom: defaultView.zoom,
    minZoom: defaultView.zoom,
    maxZoom: 8,
    zoomSnap: 0.5,
    zoomDelta: 0.5,
    zoomControl: false,
    worldCopyJump: true
});
const cityMarkerLayer = L.layerGroup().addTo(map);
let suggestionsOpen = false;
// set of city_ids (strings) the current user has saved as favourites
let SAVED_CITY_IDS = new Set();

function getSaveButtonLabel(isSaved) {
    return isSaved ? '★ Saved' : '☆ Save';
}

function getSaveButtonTitle(isSaved) {
    return isSaved ? 'Click to unsave' : '';
}

// OpenStreetMap default tiles — colorful base (greens for land, blues for water)
// then we tint the whole pane via CSS filter to push the palette toward purple-green
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

function initializeCityMarkers() {
    cityMarkerLayer.clearLayers();

    // custom indigo teardrop pin — built as a DivIcon with HTML/CSS,
    // no image asset needed, matches the brand
    const cityPinIcon = L.divIcon({
        className: 'city-pin',
        html: '<div class="pin-body"><div class="pin-dot"></div></div>',
        iconSize: [26, 36],
        iconAnchor: [13, 34]
    });

    cityData.forEach((city) => {
        const marker = L.marker([city.lat, city.lng], { icon: cityPinIcon }).addTo(cityMarkerLayer);

        // city.name is "Sydney, New South Wales" — short name is just "Sydney"
        const shortName = city.name.split(',')[0].trim();
        const cityId = CITY_IDS_BY_NAME[shortName];
        // build the listing URL with the city filter if we know the id,
        // otherwise fall back to the unfiltered listing
        const listingHref = cityId
            ? `${LISTING_URL}?city_id=${cityId}`
            : LISTING_URL;

        // Guests see the button greyed out (matches verify/dispute pattern).
        // Saved cities render in the filled-star state and can be toggled off.
        const isSaved = cityId && (SAVED_CITY_IDS.has(String(cityId)) || SAVED_CITY_IDS.has(Number(cityId)));
        const disabled = IS_GUEST;
        const buttonTitle = IS_GUEST ? 'Please log in to save locations' : getSaveButtonTitle(isSaved);
        const popupSaveButton = cityId ? `<button class="popup-save-location" data-city-id="${cityId}" type="button"${disabled ? ' disabled' : ''}${buttonTitle ? ` title="${buttonTitle}"` : ''}>${getSaveButtonLabel(isSaved)}</button>` : '';

        marker.bindPopup(`
            <div class="popup-content">
                <strong>${city.name}</strong>
                <div class="popup-state">${city.state}</div>
                <div class="popup-actions">
                    <a href="${listingHref}" class="popup-action">View reports for ${shortName} →</a>
                    <a href="${LIVE_WEATHER_URL}?city=${encodeURIComponent(shortName)}" class="popup-action">View weather for ${shortName} →</a>
                    ${popupSaveButton}
                </div>
            </div>
        `, { autoPanPadding: L.point(20, 60), keepInView: true });

        marker.on('click', function () {
            searchBar.value = city.name;
            clearSuggestions();
            focusCity(city);
        });

        // keep a reference on the city so onSearchSubmit can openPopup() on it
        city.marker = marker;
    });
}


// Load saved favourites from the server so popups can reflect the saved state.
function loadSavedFavourites() {
    return csrfFetch('/api/favourites/locations')
        .then(r => {
            if (!r.ok) throw new Error('Failed to load favourites');
            return r.json();
        })
        .then(list => {
            SAVED_CITY_IDS = new Set(list.map(item => String(item.city_id)));
        })
        .catch(() => {
            // fail silently — default to empty set
            SAVED_CITY_IDS = new Set();
        });
}

function clearSuggestions() {
    suggestions.innerHTML = '';
    suggestionsOpen = false;
}

function focusCity(city) {
    const latlng = [city.lat, city.lng];
    map.setView(latlng, 5);
}

function wrapLongitude(lng) {
    return ((lng + 180) % 360 + 360) % 360 - 180;
}

function clampMapCenterToAustralia() {
    const center = map.getCenter();
    const wrappedLng = wrapLongitude(center.lng);
    const clampedLat = Math.min(Math.max(center.lat, southBound), northBound);
    const clampedLng = Math.min(Math.max(wrappedLng, westBound), eastBound);

    if (Math.abs(clampedLat - center.lat) > 1e-6 || Math.abs(clampedLng - wrappedLng) > 1e-6) {
        map.panTo([clampedLat, clampedLng], { animate: false });
    }
}

function search() {
    const query = searchBar.value.toLowerCase();
    let filteredCities;

    if (!query.trim()) {
        filteredCities = cityData.slice(0, 5);
    } else {
        filteredCities = cityData.filter((item) => (
            item.name.toLowerCase().includes(query) || item.state.toLowerCase().includes(query)
        ));
    }

    suggestions.innerHTML = '';
    const length = filteredCities.length < 5 ? filteredCities.length : 5;
    for (let i = 0; i < length; i++) {
        const suggestion = document.createElement('li');
        suggestion.textContent = filteredCities[i].name;
        suggestions.appendChild(suggestion);
    }
    suggestionsOpen = length > 0;
}

function autocomplete(event) {
    event.stopPropagation();

    if (event.target.tagName === 'LI') {
        const selectedCity = cityData.find((item) => item.name === event.target.textContent);

        if (selectedCity) {
            searchBar.value = selectedCity.name;
            clearSuggestions();
            focusCity(selectedCity);
        }
    }
}

function minimise(event) {
    if (!searchWrapper.contains(event.target)) {
        clearSuggestions();
        return;
    }
}

function onSearchBarClick(event) {
    event.stopPropagation();

    if (suggestionsOpen) {
        clearSuggestions();
    } else {
        search();
    }
}

// shared helper — both buttons need to find the city the user typed
function findCityFromQuery() {
    const query = searchBar.value.trim().toLowerCase();
    if (!query) {
        alert('Please enter a location to search.');
        return null;
    }
    const match = cityData.find((item) => (
        item.name.toLowerCase() === query ||
        item.name.toLowerCase().includes(query) ||
        item.state.toLowerCase().includes(query)
    ));
    if (!match) {
        alert('No matching location found.');
        return null;
    }
    return match;
}

// "Search" — zoom the map to the matched city's pin and open its popup
function onSearchSubmit(event) {
    event.stopPropagation();
    const selectedCity = findCityFromQuery();
    if (!selectedCity) return;
    searchBar.value = selectedCity.name;
    focusCity(selectedCity);
    clearSuggestions();
    // open the marker's popup so the user lands on the same UI as a pin click
    if (selectedCity.marker) selectedCity.marker.openPopup();
}

function onSearchBarKeyDown(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        onSearchSubmit(event);
    }
}

function zoom(zoomIn) {
    zoomIn ? map.zoomIn() : map.zoomOut();
}

function resetMap() {
    map.setView(defaultView.center, defaultView.zoom);
}

searchBar.addEventListener('click', onSearchBarClick);
searchBar.addEventListener('input', search);
searchBar.addEventListener('keydown', onSearchBarKeyDown);
searchButton.addEventListener('click', onSearchSubmit);

// Handle Save Location clicks inside marker popups (delegated)
document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.popup-save-location');
    if (!btn) return;
    ev.preventDefault();
    const cityId = btn.getAttribute('data-city-id');
    if (!cityId) {
        alert('This location cannot be saved because it is not in the database.');
        return;
    }
    const cityKey = String(cityId);
    const wasSaved = SAVED_CITY_IDS.has(cityKey);
    const method = wasSaved ? 'DELETE' : 'POST';
    csrfFetch(`/api/favourites/location/${cityId}`, { method })
        .then(r => {
            if (!r.ok) throw new Error('Network error');
            return r.json();
        })
        .then(() => {
            if (wasSaved) {
                btn.textContent = getSaveButtonLabel(false);
                btn.title = getSaveButtonTitle(false);
                SAVED_CITY_IDS.delete(cityKey);
            } else {
                btn.textContent = getSaveButtonLabel(true);
                btn.title = getSaveButtonTitle(true);
                SAVED_CITY_IDS.add(cityKey);
            }
        })
        .catch(() => alert(`Could not ${wasSaved ? 'unsave' : 'save'} location.`));
});
document.body.addEventListener('click', minimise);
suggestions.addEventListener('click', autocomplete);
map.on('moveend', clampMapCenterToAustralia);
// load saved favourites first so marker popups render correct saved state
loadSavedFavourites().then(() => initializeCityMarkers());
