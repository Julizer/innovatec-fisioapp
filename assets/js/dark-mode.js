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

function initializeDarkMode() {
    const theme = getStoredTheme();
    applyTheme(theme);
    connectExistingSwitch();
}

document.addEventListener('DOMContentLoaded', initializeDarkMode);
