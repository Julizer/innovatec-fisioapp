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
    } else if (iconType === 'svg-mask') {
        const source = active ? icon.activeSrc : icon.src;
        iconHtml = `<span class="nav-svg-icon" style="mask: url('${source}') center / contain no-repeat; -webkit-mask: url('${source}') center / contain no-repeat;" aria-hidden="true"></span>`;
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

    const tortuIcon = {
        src: 'assets/art/tortuICON.svg',
        activeSrc: 'assets/art/tortuICON-filled.svg'
    };
    const userIcon = {
        src: 'assets/art/user.svg',
        activeSrc: 'assets/art/user-filled.svg'
    };
    const gearIcon = {
        src: 'assets/art/gear.svg',
        activeSrc: 'assets/art/gear-filled.svg'
    };

    let items = null;

    if (page.startsWith('dashboard-paciente-')) {
        items = [
            {
                href: 'dashboard-paciente-home.html',
                label: 'Tu Tortu',
                icon: tortuIcon,
                iconType: 'svg-mask',
                active: page === 'dashboard-paciente-home.html'
            },
            {
                href: 'dashboard-paciente-me.html',
                label: 'Perfil',
                icon: userIcon,
                iconType: 'svg-mask',
                active: page === 'dashboard-paciente-me.html'
            },
            {
                href: 'dashboard-paciente-settings.html',
                label: 'Ajustes',
                icon: gearIcon,
                iconType: 'svg-mask',
                active: page === 'dashboard-paciente-settings.html'
            }
        ];
    } else if (page.startsWith('dashboard-terapeuta-')) {
        items = [
            {
                href: 'dashboard-terapeuta-home.html',
                label: 'Tu Tortu',
                icon: tortuIcon,
                iconType: 'svg-mask',
                active: page === 'dashboard-terapeuta-home.html'
            },
            {
                href: 'dashboard-terapeuta-patients.html',
                label: 'Pacientes',
                icon: userIcon,
                iconType: 'svg-mask',
                active: page === 'dashboard-terapeuta-patients.html'
            },
            {
                href: 'dashboard-terapeuta-settings.html',
                label: 'Ajustes',
                icon: gearIcon,
                iconType: 'svg-mask',
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
