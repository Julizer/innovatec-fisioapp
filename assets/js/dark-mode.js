function getStoredTheme() {
    const stored = localStorage.getItem('darkMode');
    if (stored === 'dark' || stored === 'light') {
        return stored;
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
    document.documentElement.dataset.bsTheme = theme;
    document.documentElement.classList.toggle('dark-mode', theme === 'dark');
    document.body.classList.toggle('dark-mode', theme === 'dark');
    const toggle = document.getElementById('dark-mode-toggle');
    if (toggle) {
        toggle.checked = theme === 'dark';
    }
}

function saveTheme(theme) {
    localStorage.setItem('darkMode', theme);
    applyTheme(theme);
}

function toggleDarkMode() {
    saveTheme(getStoredTheme() === 'dark' ? 'light' : 'dark');
}

function connectExistingSwitch() {
    const toggle = document.getElementById('dark-mode-toggle');
    if (!toggle) {
        return;
    }
    toggle.checked = getStoredTheme() === 'dark';
    toggle.removeEventListener('change', toggleDarkMode);
    toggle.addEventListener('change', () => {
        saveTheme(toggle.checked ? 'dark' : 'light');
    });
}

function getDashboardPageName() {
    const path = window.location.pathname || '';
    return path.substring(path.lastIndexOf('/') + 1);
}

function buildNavItem({ href, label, icon, iconType, active }) {
    const itemClass = [
        'small text-decoration-none text-center d-flex w-100 flex-column justify-content-center align-items-center',
        active ? 'active' : 'text-muted'
    ].join(' ');

    const target = active ? '#' : href;
    let iconHtml = '';

    if (iconType === 'material') {
        iconHtml = `<i class="material-icons d-block ms-0 ps-0 me-0 pe-md-0 mb-0 pb-0" style="padding-bottom: 0px;">${icon}</i>`;
    } else {
        iconHtml = icon;
    }

    return `<a class="${itemClass}" href="${target}">${iconHtml}<strong>${label}</strong></a>`;
}

function renderUnifiedDashboardNavbar() {
    const nav = document.querySelector('nav.navbar.fixed-bottom');
    if (!nav) {
        return;
    }

    const page = getDashboardPageName();

    const homeIcon = '<svg class="bi bi-house fs-4 d-block mb-1" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16" style="font-size: 24px;"><path d="M8.707 1.5a1 1 0 0 0-1.414 0L.646 8.146a.5.5 0 0 0 .708.708L2 8.207V13.5A1.5 1.5 0 0 0 3.5 15h9a1.5 1.5 0 0 0 1.5-1.5V8.207l.646.647a.5.5 0 0 0 .708-.708L13 5.793V2.5a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1.293zM13 7.207V13.5a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5V7.207l5-5z"></path></svg>';
    const heartIcon = '<svg class="bi bi-heart fs-4 d-block" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16"><path d="m8 2.748-.717-.737C5.6.281 2.514.878 1.4 3.053c-.523 1.023-.641 2.5.314 4.385.92 1.815 2.834 3.989 6.286 6.357 3.452-2.368 5.365-4.542 6.286-6.357.955-1.886.838-3.362.314-4.385C13.486.878 10.4.28 8.717 2.01zM8 15C-7.333 4.868 3.279-3.04 7.824 1.143q.09.083.176.171a3 3 0 0 1 .176-.17C12.72-3.042 23.333 4.867 8 15"></path></svg>';

    let items = null;

    if (page.startsWith('dashboard-paciente-')) {
        items = [
            {
                href: 'dashboard-paciente-home.html',
                label: 'Home',
                icon: homeIcon,
                iconType: 'svg',
                active: page === 'dashboard-paciente-home.html'
            },
            {
                href: 'dashboard-paciente-me.html',
                label: 'Me',
                icon: heartIcon,
                iconType: 'svg',
                active: page === 'dashboard-paciente-me.html'
            },
            {
                href: 'dashboard-paciente-settings.html',
                label: 'Settings',
                icon: 'settings',
                iconType: 'material',
                active: page === 'dashboard-paciente-settings.html'
            }
        ];
    } else if (page.startsWith('dashboard-terapeuta-')) {
        items = [
            {
                href: 'dashboard-terapeuta-home.html',
                label: 'Tu Tortu',
                icon: homeIcon,
                iconType: 'svg',
                active: page === 'dashboard-terapeuta-home.html'
            },
            {
                href: 'dashboard-terapeuta-patients.html',
                label: 'Pacientes',
                icon: heartIcon,
                iconType: 'svg',
                active: page === 'dashboard-terapeuta-patients.html'
            },
            {
                href: 'dashboard-terapeuta-settings.html',
                label: 'Ajustes',
                icon: 'settings',
                iconType: 'material',
                active: page === 'dashboard-terapeuta-settings.html'
            }
        ];
    }

    if (!items) {
        return;
    }

    nav.innerHTML = `
        <div class="container-fluid">
            <div class="text-center d-flex w-100 justify-content-around ms-0 ps-0 me-0 mb-0 pb-0">
                ${items.map(buildNavItem).join('')}
            </div>
        </div>
    `;
}

function initializeDarkMode() {
    const theme = getStoredTheme();
    applyTheme(theme);
    connectExistingSwitch();
    renderUnifiedDashboardNavbar();
}

document.addEventListener('DOMContentLoaded', initializeDarkMode);
