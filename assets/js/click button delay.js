document.querySelectorAll('.navbar a').forEach(link => {
    link.addEventListener('click', function(e) {
        // Buscamos el elemento 'a' más cercano (por si clicaste el icono)
        const a = e.target.closest('a');
        const targetUrl = a ? a.getAttribute('href') : null;

        if (targetUrl && targetUrl !== '#' && !targetUrl.startsWith('javascript')) {
            e.preventDefault();

            // Aplicamos el efecto visual al link
            a.classList.add('clic-animacion');

            // Retraso corto para que el ojo humano registre el cambio
            setTimeout(() => {
                window.location.href = targetUrl;
            }, 80); // 250ms es el "sweet spot" para feedback táctil
        }
    });
});