self.addEventListener('push', event => {
    let data = { title: 'Notificación', body: 'Tienes una nueva notificación.' };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (error) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: data.icon || '/assets/img/favicon.png',
        badge: data.badge || '/assets/img/favicon.png',
        data: {
            url: data.url || '/dashboard-paciente-home.html'
        }
    };

    event.waitUntil((async () => {
        await self.registration.showNotification(data.title, options);

        // Notify open windows so they can show in-app toast and optionally play a sound.
        const windowClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of windowClients) {
            client.postMessage({
                type: 'push-received',
                payload: {
                    title: data.title,
                    body: data.body,
                    icon: data.icon || '/assets/img/favicon.png',
                    url: data.url || '/dashboard-paciente-home.html'
                }
            });
        }
    })());
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = event.notification.data && event.notification.data.url ? event.notification.data.url : '/dashboard-paciente-home.html';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
            for (const client of windowClients) {
                if (client.url === url && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(url);
            }
        })
    );
});
