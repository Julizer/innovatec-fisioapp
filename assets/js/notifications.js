// Notification helper: show in-page Bootstrap toast + browser Notification + play sound
(function(){
  const AUDIO_SRC = 'assets/sounds/notif_generic.mp3';
  let audio;
  const BASE_TITLE = document.title;
  const isChatScreen = window.location && /chat\.html$/i.test(window.location.pathname || '');
  const disableGlobalUnreadPolling = Boolean(window.__disableGlobalUnreadTitlePolling);
  let currentUnreadTotal = 0;
  let previousUnreadTotal = null;
  let titleFlashTimer = null;
  let titleFlashActive = false;

  function baseUnreadTitle(total){
    const t = Number(total || 0);
    return t > 0 ? `(${t}) ${BASE_TITLE}` : BASE_TITLE;
  }

  function applyUnreadTitle(total){
    currentUnreadTotal = Number(total || 0);
    if(titleFlashActive) return;
    document.title = baseUnreadTitle(currentUnreadTotal);
  }

  function flashNewMessageTitle(total){
    const t = Math.max(1, Number(total || 0));
    if(titleFlashTimer){
      clearTimeout(titleFlashTimer);
      titleFlashTimer = null;
    }
    titleFlashActive = true;
    document.title = `(${t}) ¡Nuevo mensaje!`;
    titleFlashTimer = setTimeout(() => {
      titleFlashActive = false;
      document.title = baseUnreadTitle(currentUnreadTotal);
    }, 1800);
  }

  function ensureAudio(){
    if(!audio){
      audio = document.createElement('audio');
      audio.src = AUDIO_SRC;
      audio.preload = 'auto';
      document.body.appendChild(audio);
    }
  }

  function ensureToastContainer(){
    if(document.getElementById('notif-toast-container')) return;
    const container = document.createElement('div');
    container.id = 'notif-toast-container';
    container.style.position = 'fixed';
    container.style.right = '1rem';
    container.style.bottom = '1rem';
    container.style.zIndex = 1080;
    document.body.appendChild(container);
  }

  function renderToast(title, body, clickUrl){
    ensureToastContainer();
    const id = 'notif-'+Date.now();
    const tpl = document.createElement('div');
    tpl.innerHTML = `
      <div id="${id}" class="toast align-items-center text-bg-light border" role="alert" aria-live="polite" aria-atomic="true">
        <div class="d-flex">
          <div class="toast-body">
            <strong>${title}</strong><div>${body}</div>
          </div>
          <button type="button" class="btn-close btn-close-dark me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>`;
    const node = tpl.firstElementChild;
    document.getElementById('notif-toast-container').appendChild(node);
    if(clickUrl){
      node.style.cursor = 'pointer';
      node.addEventListener('click', (ev) => {
        if(ev.target && ev.target.closest && ev.target.closest('.btn-close')) return;
        window.location.href = clickUrl;
      });
    }
    if(window.bootstrap && bootstrap.Toast){
      const toast = new bootstrap.Toast(node, {delay: 6000});
      toast.show();
    }
    // remove after hidden
    node.addEventListener('hidden.bs.toast', ()=> node.remove());
    // fallback cleanup if bootstrap toast plugin isn't available
    setTimeout(() => { try { node.remove(); } catch(e){} }, 7000);
  }

  async function requestPermission(){
    if(!('Notification' in window)) return 'unsupported';
    if(Notification.permission === 'granted') return 'granted';
    try{
      const perm = await Notification.requestPermission();
      return perm;
    }catch(e){return 'denied';}
  }

  function sendBrowserNotification(title, options={}){
    if(!('Notification' in window)) return false;
    if(Notification.permission !== 'granted') return false;
    try{
      const n = new Notification(title, options);
      if(options.clickUrl){
        n.onclick = () => {
          window.focus();
          window.location.href = options.clickUrl;
        };
      }
      // close after a short time
      setTimeout(()=> n.close(), 7000);
      return true;
    }catch(e){return false}
  }

  // Public API
  window.notify = async function({title='Notificación', body='', tag=null, playSound=true, requirePermission=false, icon=null, browserNotification=true, clickUrl=null, showToast=true}={}){
    ensureAudio();
    ensureToastContainer();
    if(requirePermission && ('Notification' in window) && Notification.permission !== 'granted'){
      await requestPermission();
    }

    const shown = browserNotification ? sendBrowserNotification(title, {body, tag, icon, clickUrl}) : false;
    if(playSound){
      try{ audio.currentTime = 0; audio.play(); }catch(e){}
    }
    if(showToast){
      try{ renderToast(title, body, clickUrl); }catch(e){}
    }
    return shown;
  };

  window.notifyRequestPermission = requestPermission;
  window.notifyPlaySound = function(){ ensureAudio(); try{ audio.currentTime=0; audio.play(); }catch(e){} };
  window.notifySetUnreadTitle = applyUnreadTitle;
  window.notifyFlashNewMessageTitle = flashNewMessageTitle;
  
  // ---- Push subscription helpers (Service Worker + VAPID) ----
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async function registerServiceWorkerAndSubscribe() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      throw new Error('Push not supported in this browser');
    }

    // register service worker
    const sw = await navigator.serviceWorker.register('/service-worker.js?v=20260517');

    // get vapid public key from server
    const res = await fetch('/vapid_public_key');
    if (!res.ok) throw new Error('No VAPID key');
    const data = await res.json();
    const publicKey = data.publicKey;

    // Force a fresh subscription so stale endpoints/keys don't silently break delivery.
    const existing = await sw.pushManager.getSubscription();
    if(existing){
      try{ await existing.unsubscribe(); }catch(e){}
    }
    const sub = await sw.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey)
    });

    // send to server
    const saveRes = await fetch('/push/subscribe', {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({subscription: sub})
    });

    if (!saveRes.ok) {
      let err = 'No se pudo guardar la suscripcion push';
      try {
        const body = await saveRes.json();
        err = body.error || body.mensaje || err;
      } catch (e) {}
      throw new Error(err);
    }

    return sub;
  }

  async function unsubscribePush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      throw new Error('Push not supported in this browser');
    }
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return false;
    const subs = await reg.pushManager.getSubscription();
    if (!subs) return false;
    // tell server to remove
    await fetch('/push/unsubscribe', {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({endpoint: subs.endpoint})
    });
    await subs.unsubscribe();
    return true;
  }

  window.pushRegister = registerServiceWorkerAndSubscribe;
  window.pushUnregister = unsubscribePush;

  // Listen for push events forwarded from service worker (foreground tabs).
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      const msg = event.data || {};
      if (msg.type !== 'push-received') return;
      const payload = msg.payload || {};
      // In foreground: show in-app toast and play sound.
      window.notify({
        title: payload.title || 'Notificacion',
        body: payload.body || '',
        icon: payload.icon || null,
        playSound: true,
        browserNotification: false,
        clickUrl: payload.url || null,
        showToast: !isChatScreen
      });
    });
  }

  // Update tab title with unread chat count on non-chat screens.
  async function refreshUnreadTitle(){
    if(isChatScreen) return;
    try{
      const res = await fetch('/chat/unread_count', {credentials: 'include'});
      if(!res.ok){
        applyUnreadTitle(0);
        previousUnreadTotal = 0;
        return;
      }
      const data = await res.json();
      const total = Number(data.total || 0);
      if(previousUnreadTotal !== null && total > previousUnreadTotal && document.visibilityState !== 'visible'){
        flashNewMessageTitle(total);
      }
      applyUnreadTitle(total);
      previousUnreadTotal = total;
    }catch(e){
      // keep title unchanged on transient network errors
    }
  }

  if(!isChatScreen && !disableGlobalUnreadPolling){
    refreshUnreadTitle();
    setInterval(refreshUnreadTitle, 4000);
    document.addEventListener('visibilitychange', () => {
      if(document.visibilityState === 'visible'){
        if(titleFlashTimer){
          clearTimeout(titleFlashTimer);
          titleFlashTimer = null;
        }
        titleFlashActive = false;
        refreshUnreadTitle();
      }
    });
  }

  // Keep push subscription alive for all roles when permission was already granted.
  if ('Notification' in window && Notification.permission === 'granted') {
    registerServiceWorkerAndSubscribe().catch(() => {});
  }
})();
