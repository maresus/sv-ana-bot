(function () {
  if (window.__svAnaWidgetLoaded) return;
  window.__svAnaWidgetLoaded = true;

  const API_URL = document.currentScript?.dataset?.api || '';

  const style = document.createElement('style');
  style.textContent = `
    #svana-btn {
      position: fixed; bottom: 24px; right: 24px; z-index: 9999;
      width: 58px; height: 58px;
      background: #c8a020;
      color: #1b4a1e;
      border: none; border-radius: 50%;
      font-size: 26px; cursor: pointer;
      box-shadow: 0 4px 18px rgba(200,160,32,0.5);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #svana-btn:hover { transform: scale(1.08); box-shadow: 0 6px 24px rgba(200,160,32,0.6); }
    #svana-frame {
      position: fixed; bottom: 96px; right: 24px; z-index: 9998;
      width: 380px; height: 540px;
      border: none; border-radius: 16px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.35);
      display: none;
      overflow: hidden;
    }
    @media (max-width: 480px) {
      #svana-frame { width: 100vw; height: 100vh; bottom: 0; right: 0; border-radius: 0; }
      #svana-btn   { bottom: 16px; right: 16px; }
    }
  `;
  document.head.appendChild(style);

  const btn = document.createElement('button');
  btn.id = 'svana-btn';
  btn.title = 'Ana – Asistentka Občine Sveta Ana';
  btn.innerHTML = '🏛';
  document.body.appendChild(btn);

  const frame = document.createElement('iframe');
  frame.id = 'svana-frame';
  frame.src = API_URL + '/widget';
  if (API_URL) frame.contentWindow; // preload
  document.body.appendChild(frame);

  let open = false;
  btn.addEventListener('click', () => {
    open = !open;
    frame.style.display = open ? 'block' : 'none';
    btn.innerHTML = open ? '✕' : '🏛';
  });
})();
