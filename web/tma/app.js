/*
  ShelfLife Telegram Mini App.

  Everything the app shows comes from api/tma/app.php, which identifies the
  user only by the init data Telegram signed for this launch (sent in the
  X-Telegram-Init-Data header and checked on the server with the bot token).
  Nothing here is trusted for authorisation: initDataUnsafe is used for nothing.

  The records, their status, the days left and the spending are computed by the
  server with the website's rules (includes/shelflife/overview.php) and every
  change answers with the fresh account state, so the app never does its own
  date or money arithmetic. Text formatting follows the bot (bot/bot/texts.py).

  Navigation: five tabs; a record and the form open over them, and Telegram's
  Back button (or the in-page one on clients without it) returns. User text is
  always inserted as text, never as HTML.
*/
(function () {
  'use strict';

  var API = '../api/tma/app.php';
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  var root = document.getElementById('app');
  var botUsername = root.getAttribute('data-bot') || '';

  // --- formatting (as the bot: bot/bot/texts.py) -----------------------------------

  var NBSP = ' ';
  var KIND_NAMES = { subscription: 'Подписка', expiry: 'Срок годности', maintenance: 'Обслуживание' };
  var STATUS_NAMES = { overdue: 'Просрочено', soon: 'Скоро', ok: 'В порядке', inactive: 'Отменена' };
  var GROUP_TITLES = {
    overdue: 'Просрочено', today: 'Сегодня', tomorrow: 'Завтра',
    week: 'На этой неделе', month: 'В ближайший месяц'
  };
  var PERIODS = {
    1: ['каждый день', 'день', 'дня', 'дней'],
    2: ['каждую неделю', 'неделю', 'недели', 'недель'],
    3: ['каждый месяц', 'месяц', 'месяца', 'месяцев'],
    4: ['каждый год', 'год', 'года', 'лет']
  };
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря'];

  function plural(n, one, few, many) {
    n = Math.abs(n);
    if (n % 10 === 1 && n % 100 !== 11) return one;
    if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return few;
    return many;
  }

  function days(n) {
    return Math.abs(n) + ' ' + plural(n, 'день', 'дня', 'дней');
  }

  function formatDate(iso) {
    var p = String(iso || '').split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : '';
  }

  function longDate(iso) {
    var p = String(iso || '').split('-');
    return p.length === 3 ? Number(p[2]) + ' ' + MONTHS[Number(p[1]) - 1] : '';
  }

  function relativeDays(delta) {
    if (delta === 0) return 'сегодня';
    if (delta === 1) return 'завтра';
    if (delta === -1) return 'вчера';
    return delta > 0 ? 'через ' + days(delta) : days(delta) + ' назад';
  }

  // Two decimals rounded like Python's format() (half to even on an exact tie
  // such as 0.125), so an amount reads the same here and in the bot.
  function fixed2(x) {
    var ax = Math.abs(x);
    var s = ax.toFixed(2);
    if (Number.isInteger(ax * 8) && !Number.isInteger(ax * 4)) {
      var cents = Math.floor(ax * 100);
      s = ((cents % 2 === 0 ? cents : cents + 1) / 100).toFixed(2);
    }
    return (x < 0 ? '-' : '') + s;
  }

  function amount(value, symbol) {
    var parts = fixed2(Number(value) || 0).split('.');
    var text = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, NBSP) + (parts[1] === '00' ? '' : ',' + parts[1]);
    return symbol ? text + NBSP + symbol : text;
  }

  function symbolOf(currency) {
    return currency ? (currency.symbol || currency.code || '') : '';
  }

  function period(cycle, frequency) {
    var unit = PERIODS[cycle];
    if (!unit) return null;
    var n = Math.max(1, frequency);
    return n === 1 ? unit[0] : 'каждые ' + n + ' ' + plural(n, unit[1], unit[2], unit[3]);
  }

  function renewPeriod(cycle, frequency) {
    var unit = PERIODS[cycle];
    var n = Math.max(1, frequency);
    if (!unit || n === 1) return unit ? unit[1] : 'месяц';
    return n + ' ' + plural(n, unit[1], unit[2], unit[3]);
  }

  function when(record) {
    if (!record.next_payment) return 'без даты';
    var date = formatDate(record.next_payment);
    if (record.inactive || record.days_left === null || record.days_left === undefined) return date;
    return date + ' — ' + relativeDays(record.days_left);
  }

  function reminderText(record, defaultDays) {
    if (record.inactive) return 'не приходят — запись отменена';
    if (!record.notify) return 'выключены';
    var d = record.notify_days_before;
    var suffix = '';
    if (d === null || d === undefined || d < 0) {
      d = defaultDays;
      suffix = ' (по умолчанию)';
    }
    var text = (d === 0 ? 'в день даты' : 'за ' + days(d) + ' до даты') + suffix;
    if (record.snoozed_until) text += '; отложено до ' + formatDate(record.snoozed_until);
    return text;
  }

  // --- DOM ---------------------------------------------------------------------------

  function h(tag, props) {
    var el = document.createElement(tag);
    var value;
    props = props || {};
    Object.keys(props).forEach(function (key) {
      var v = props[key];
      if (v === null || v === undefined || v === false) return;
      if (key === 'class') el.className = v;
      else if (key === 'on') Object.keys(v).forEach(function (ev) { el.addEventListener(ev, v[ev]); });
      else if (key === 'value') value = v;
      else if (key === 'checked' || key === 'disabled' || key === 'selected') el[key] = true;
      else el.setAttribute(key, v === true ? '' : String(v));
    });
    for (var i = 2; i < arguments.length; i++) appendOne(el, arguments[i]);
    if (value !== undefined) el.value = value;
    return el;
  }

  // append(el, child, child, ...): nodes, text, arrays of them; null and false are skipped.
  function append(el) {
    for (var i = 1; i < arguments.length; i++) appendOne(el, arguments[i]);
  }

  function appendOne(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { appendOne(el, c); }); return; }
    el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  // Static icons (no user data in them).
  var ICONS = {
    home: '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/>',
    soon: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4M8 14h3"/>',
    spend: '<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M7 15h4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M21.2 12h-2.4M5.2 12H2.8M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2 5.5 5.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    chevron: '<path d="m1.5 1.5 5 5.5-5 5.5"/>',
    back: '<path d="M15 5 8 12l7 7"/>'
  };

  function icon(name, cls) {
    var span = document.createElement('span');
    var box = name === 'chevron' ? '0 0 8 14' : '0 0 24 24';
    span.innerHTML = '<svg viewBox="' + box + '" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + ICONS[name] + '</svg>';
    var svg = span.firstChild;
    if (cls) svg.setAttribute('class', cls);
    return svg;
  }

  function logoMark(cls) {
    var span = document.createElement('span');
    span.innerHTML = '<svg viewBox="0 0 100 100" aria-hidden="true"><path class="mark-bars" d="M13 8H53A9 9 0 0 1 53 26H13A9 9 0 0 1 13 8ZM13 41H35A9 9 0 0 1 35 59H13A9 9 0 0 1 13 41ZM13 74H17A9 9 0 0 1 17 92H13A9 9 0 0 1 13 74Z"/>' +
      '<path class="mark-clock" fill-rule="evenodd" d="M46 70A26 26 0 1 1 98 70A26 26 0 1 1 46 70ZM68.5 56A3.5 3.5 0 0 1 75.5 56L75.5 66.5L83 66.5A3.5 3.5 0 0 1 83 73.5L72 73.5A3.5 3.5 0 0 1 68.5 70Z"/></svg>';
    var svg = span.firstChild;
    svg.setAttribute('class', cls || 'state-mark');
    return svg;
  }

  // --- Telegram ----------------------------------------------------------------------

  var T = {
    inside: !!(tg && typeof tg.initData === 'string' && tg.initData.length > 0),
    atLeast: function (v) {
      try { return !!(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(v)); } catch (e) { return false; }
    },
    haptic: function (type) {
      try { if (T.atLeast('6.1')) tg.HapticFeedback.notificationOccurred(type); } catch (e) { /* optional */ }
    },
    tap: function () {
      try { if (T.atLeast('6.1')) tg.HapticFeedback.selectionChanged(); } catch (e) { /* optional */ }
    },
    hasBack: function () { return T.atLeast('6.1') && !!tg.BackButton; },
    openLink: function (url) {
      if (tg && tg.openLink) tg.openLink(url); else window.open(url, '_blank', 'noopener');
    },
    openTelegramLink: function (url) {
      if (tg && tg.openTelegramLink && T.atLeast('6.1')) tg.openTelegramLink(url); else window.location.href = url;
    },
    close: function () { if (tg && tg.close) tg.close(); },
    closingConfirmation: function (on) {
      try {
        if (!T.atLeast('6.2')) return;
        if (on) tg.enableClosingConfirmation(); else tg.disableClosingConfirmation();
      } catch (e) { /* optional */ }
    }
  };

  var backHandler = null;
  function onBack() { if (backHandler) backHandler(); }

  function setBack(handler) {
    backHandler = handler;
    if (!T.hasBack()) return;
    if (handler) tg.BackButton.show(); else tg.BackButton.hide();
  }

  var mainHandler = null;
  function onMain() { if (mainHandler) mainHandler(); }

  function setMain(text, handler) {
    mainHandler = handler;
    if (!tg || !tg.MainButton) return;
    if (handler) {
      tg.MainButton.setParams({ text: text, is_visible: true, is_active: true });
    } else {
      tg.MainButton.hideProgress();
      tg.MainButton.hide();
    }
  }

  function mainBusy(on) {
    if (!tg || !tg.MainButton || !mainHandler) return;
    if (on) { tg.MainButton.showProgress(false); tg.MainButton.disable(); }
    else { tg.MainButton.hideProgress(); tg.MainButton.enable(); }
  }

  function applyTheme() {
    var html = document.documentElement;
    if (tg && tg.themeParams && tg.themeParams.bg_color) html.setAttribute('data-telegram-theme', '');
    else html.removeAttribute('data-telegram-theme');
    html.setAttribute('data-scheme', tg && tg.colorScheme === 'dark' ? 'dark' : 'light');
    try {
      if (T.atLeast('6.1')) {
        tg.setHeaderColor('secondary_bg_color');
        tg.setBackgroundColor('secondary_bg_color');
      }
    } catch (e) { /* optional */ }
  }

  // --- API -----------------------------------------------------------------------------

  function ApiError(kind, reason) {
    this.kind = kind;
    this.reason = reason || null;
  }

  function newRequestId() {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  // A change carries a request id; the server applies one id once, so a retry
  // of the same request (after a lost answer) cannot apply it twice.
  function api(op, body, requestId) {
    var payload = Object.assign({ op: op }, body || {});
    if (op !== 'state') payload.request_id = requestId || newRequestId();
    return fetch(API, {
      method: 'POST',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg ? tg.initData : '' },
      body: JSON.stringify(payload)
    }).catch(function () {
      throw new ApiError('network');
    }).then(function (response) {
      return response.json().catch(function () { return null; }).then(function (data) {
        if (response.status === 401) throw new ApiError('unauthorized', data && data.reason);
        if (response.status === 503) throw new ApiError('not_configured');
        if (!response.ok || !data || typeof data !== 'object') throw new ApiError('server');
        return data;
      });
    });
  }

  // --- app state -------------------------------------------------------------------------

  var app = {
    state: null,        // the account overview from the server
    phase: 'loading',   // loading | ready | not_linked | unlinked | outside | error
    error: null,
    tab: 'home',
    stack: [],          // screens over the tab: {name: 'card'|'form', id}
    filter: 'all',
    query: '',
    form: null,         // the open form's values
    busy: false,
    scroll: {}
  };

  function record(id) {
    if (!app.state) return null;
    for (var i = 0; i < app.state.records.length; i++) {
      if (app.state.records[i].id === id) return app.state.records[i];
    }
    return null;
  }

  function currency(id) {
    var list = app.state ? app.state.currencies : [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function mainCurrency() {
    return app.state ? currency(app.state.account.main_currency_id) : null;
  }

  function current() {
    return app.stack.length ? app.stack[app.stack.length - 1] : null;
  }

  // --- toast and dialog --------------------------------------------------------------------

  var toastTimer = null;
  function toast(text, isError) {
    var old = document.querySelector('.toast');
    if (old) old.remove();
    var el = h('div', { class: 'toast' + (isError ? ' error' : ''), role: 'status' }, text);
    document.body.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.remove(); }, 2800);
  }

  var sheetClose = null;
  function confirmSheet(title, text, confirmLabel) {
    var shown = document.querySelector('.toast');
    if (shown) shown.remove(); // it would cover the dialog's buttons
    return new Promise(function (resolve) {
      var previousBack = backHandler;
      function close(result) {
        backdrop.remove();
        sheetClose = null;
        setBack(previousBack);
        resolve(result);
      }
      var backdrop = h('div', {
        class: 'sheet-backdrop',
        on: { click: function (e) { if (e.target === backdrop) close(false); } }
      }, h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'sheet-title' },
        h('h2', { id: 'sheet-title' }, title),
        h('p', null, text),
        h('button', { class: 'btn danger', type: 'button', on: { click: function () { close(true); } } }, confirmLabel),
        h('button', { class: 'btn secondary', type: 'button', on: { click: function () { close(false); } } }, 'Отмена')
      ));
      sheetClose = close;
      setBack(function () { close(false); });
      document.body.appendChild(backdrop);
      backdrop.querySelector('.btn.secondary').focus();
    });
  }

  // --- navigation ------------------------------------------------------------------------------

  function go(screen) {
    app.scroll[stackKey()] = window.scrollY;
    app.stack.push(screen);
    render(true);
  }

  function back() {
    if (sheetClose) { sheetClose(false); return; }
    if (!app.stack.length) return;
    if (current().name === 'form' && app.form && app.form.dirty) {
      confirmSheet('Выйти без сохранения?', 'Изменения в форме пропадут.', 'Выйти').then(function (ok) {
        if (ok) { app.form = null; app.stack.pop(); render(false); }
      });
      return;
    }
    if (current().name === 'form') app.form = null;
    app.stack.pop();
    render(false);
  }

  function switchTab(tab) {
    if (app.stack.length && current().name === 'form' && app.form && app.form.dirty) {
      confirmSheet('Выйти без сохранения?', 'Изменения в форме пропадут.', 'Выйти').then(function (ok) {
        if (ok) { app.form = null; app.stack = []; app.tab = tab; render(true); }
      });
      return;
    }
    T.tap();
    if (app.tab === tab && !app.stack.length) { window.scrollTo(0, 0); return; }
    app.scroll[stackKey()] = window.scrollY;
    app.form = null;
    app.stack = [];
    app.tab = tab;
    render(false);
  }

  function stackKey() {
    return app.tab + '/' + app.stack.map(function (s) { return s.name + (s.id || ''); }).join('/');
  }

  // --- rendering -------------------------------------------------------------------------------

  function render(toTop) {
    var screen = current();
    var view;
    setMain(null, null);
    T.closingConfirmation(false);

    if (app.phase === 'loading') view = skeleton();
    else if (app.phase === 'outside') view = outsideScreen();
    else if (app.phase === 'not_linked') view = notLinkedScreen();
    else if (app.phase === 'unlinked') view = unlinkedScreen();
    else if (app.phase === 'error') view = errorScreen();
    else if (screen && screen.name === 'card') view = cardScreen(screen.id);
    else if (screen && screen.name === 'form') view = formScreen(screen.id);
    else view = tabScreen(app.tab);

    var ready = app.phase === 'ready';
    var showTabs = ready && !(screen && screen.name === 'form');
    root.replaceChildren(view);
    if (showTabs) root.appendChild(tabbar());
    view.classList.toggle('no-tabs', !showTabs);

    setBack(ready && app.stack.length ? back : null);
    if (screen && screen.name === 'form' && app.form) bindFormButton();

    var y = toTop ? 0 : (app.scroll[stackKey()] || 0);
    window.scrollTo(0, y);
  }

  function tabScreen(tab) {
    if (tab === 'records') return recordsScreen();
    if (tab === 'soon') return soonScreen();
    if (tab === 'spend') return spendScreen();
    if (tab === 'settings') return settingsScreen();
    return homeScreen();
  }

  function tabbar() {
    var tabs = [['home', 'Главная', 'home'], ['records', 'Записи', 'list'], ['soon', 'Скоро', 'soon'],
      ['spend', 'Расходы', 'spend'], ['settings', 'Настройки', 'settings']];
    var onTab = !app.stack.length;
    return h('nav', { class: 'tabbar', 'aria-label': 'Разделы' }, tabs.map(function (t) {
      return h('button', {
        class: 'tab', type: 'button', 'data-tab': t[0],
        'aria-current': onTab && app.tab === t[0] ? 'page' : null,
        on: { click: function () { switchTab(t[0]); } }
      }, icon(t[2]), h('span', null, t[1]));
    }));
  }

  function inPageBack() {
    if (T.hasBack()) return null;
    return h('button', { class: 'link-button', type: 'button', on: { click: back } }, '‹ Назад');
  }

  function skeleton() {
    return h('main', { class: 'view', 'aria-busy': 'true' },
      h('div', { class: 'skeleton title' }),
      h('div', { class: 'skeleton block' }),
      h('div', { class: 'skeleton row' }), h('div', { class: 'skeleton row' }), h('div', { class: 'skeleton row' }));
  }

  function fab() {
    return h('button', {
      class: 'fab', type: 'button', 'aria-label': 'Добавить запись', title: 'Добавить запись',
      on: { click: function () { openForm(null); } }
    }, icon('plus'));
  }

  function recordRow(r, side) {
    var meta = KIND_NAMES[r.kind] + ' · ' + when(r);
    return h('li', null, h('button', {
      class: 'row', type: 'button', 'data-record': r.id,
      on: { click: function () { go({ name: 'card', id: r.id }); } }
    },
    h('span', { class: 'dot ' + r.status, title: STATUS_NAMES[r.status] }),
    h('span', { class: 'row-main' },
      h('span', { class: 'row-name' }, r.name),
      h('span', { class: 'row-meta' + (r.status === 'overdue' ? ' overdue' : '') }, meta)),
    side !== undefined ? h('span', { class: 'row-side' }, side) : (r.price > 0 ? h('span', { class: 'row-side' }, amount(r.price, symbolOf(r.currency))) : null),
    icon('chevron', 'chev')));
  }

  // Home: what needs attention, the nearest dates, the monthly spending.
  function homeScreen() {
    var s = app.state;
    var name = s.account.first_name || s.account.username;
    var view = h('main', { class: 'view' },
      h('header', { class: 'hello' },
        h('h1', null, 'Здравствуйте, ' + name + '!'),
        h('p', null, 'Сегодня ' + longDate(s.today))));

    if (!s.records.length) {
      append(view, h('section', { class: 'card' }, h('div', { class: 'empty' },
        logoMark(),
        h('strong', null, 'Пока здесь пусто'),
        'Добавьте подписку, срок годности продукта или дату обслуживания — ShelfLife напомнит заранее.')));
      append(view, h('div', { class: 'actions' },
        h('button', { class: 'btn', type: 'button', on: { click: function () { openForm(null); } } }, 'Добавить первую запись')));
      return view;
    }

    var sum = s.summary;
    append(view, h('section', { class: 'stats', 'aria-label': 'Сводка' },
      h('button', { class: 'stat', type: 'button', on: { click: function () { switchTab('records'); } } },
        h('b', null, sum.active), h('span', null, plural(sum.active, 'активная', 'активные', 'активных'))),
      h('button', { class: 'stat' + (sum.overdue ? ' overdue' : ''), type: 'button', on: { click: function () { switchTab('soon'); } } },
        h('b', null, sum.overdue), h('span', null, 'просрочено')),
      h('button', { class: 'stat' + (sum.week ? ' soon' : ''), type: 'button', on: { click: function () { switchTab('soon'); } } },
        h('b', null, sum.week), h('span', null, 'на этой неделе'))));

    var next = [];
    s.upcoming.groups.forEach(function (g) {
      g.records.forEach(function (r) { var fresh = record(r.id); if (fresh) next.push(fresh); });
    });
    append(view, h('h2', { class: 'section-title' }, 'Ближайшее'));
    if (next.length) {
      append(view, h('section', { class: 'card' }, h('ul', { class: 'list' }, next.slice(0, 5).map(function (r) { return recordRow(r); }))));
      if (next.length > 5 || s.upcoming.later) {
        append(view, h('p', { class: 'note' }, h('button', { class: 'link-button', type: 'button', on: { click: function () { switchTab('soon'); } } }, 'Все ближайшие даты ›')));
      }
    } else {
      append(view, h('section', { class: 'card' }, h('div', { class: 'empty' }, 'В ближайшие 30 дней ничего не запланировано.')));
    }

    var e = s.expenses;
    if (e.per_currency.length) {
      append(view, h('h2', { class: 'section-title' }, 'Подписки в месяц'));
      var lines = e.total && e.per_currency.length > 1
        ? [h('div', { class: 'money-line' }, h('span', { class: 'label' }, 'Всего'), h('span', { class: 'amount' }, '≈ ' + amount(e.total.monthly, symbolOf(e.total.currency))))]
        : e.per_currency.map(function (m) {
          return h('div', { class: 'money-line' },
            h('span', { class: 'label' }, m.count + ' ' + plural(m.count, 'подписка', 'подписки', 'подписок')),
            h('span', { class: 'amount' }, amount(m.monthly, symbolOf(m.currency))));
        });
      append(view, h('button', { class: 'card card-body', type: 'button', 'data-go': 'spend', on: { click: function () { switchTab('spend'); } } }, lines));
    }
    append(view, fab());
    return view;
  }

  var FILTERS = [['all', 'Все'], ['subscription', 'Подписки'], ['expiry', 'Сроки'], ['maintenance', 'Обслуживание'], ['off', 'Отменённые']];

  function filtered(flt) {
    return app.state.records.filter(function (r) {
      if (flt === 'off') return r.inactive;
      return !r.inactive && (flt === 'all' || r.kind === flt);
    });
  }

  function recordsScreen() {
    var view = h('main', { class: 'view' }, h('h1', { class: 'page-title' }, 'Записи'));
    var listBox = h('div');

    function fill() {
      var q = app.query.trim().toLocaleLowerCase('ru');
      var items = filtered(app.filter).filter(function (r) {
        return !q || r.name.toLocaleLowerCase('ru').indexOf(q) !== -1;
      });
      listBox.replaceChildren();
      if (!items.length) {
        var text = q ? 'Ничего не нашлось по запросу «' + app.query.trim() + '».'
          : app.filter === 'off' ? 'Отменённых записей нет: всё, что вы отслеживаете, активно.' : 'Здесь пока ничего нет.';
        append(listBox, h('section', { class: 'card' }, h('div', { class: 'empty' }, text)));
        return;
      }
      append(listBox, h('section', { class: 'card' }, h('ul', { class: 'list' }, items.map(function (r) { return recordRow(r); }))));
      append(listBox, h('p', { class: 'note' }, items.length + ' ' + plural(items.length, 'запись', 'записи', 'записей')));
    }

    var search = h('input', {
      type: 'search', placeholder: 'Поиск по названию', 'aria-label': 'Поиск по названию',
      autocomplete: 'off', enterkeyhint: 'search', value: app.query,
      on: { input: function () { app.query = search.value; fill(); } }
    });
    append(view, h('div', { class: 'search' }, icon('search'), search));
    append(view, h('div', { class: 'chips', role: 'toolbar', 'aria-label': 'Фильтр' }, FILTERS.map(function (f) {
      var count = filtered(f[0]).length;
      return h('button', {
        class: 'chip', type: 'button', 'aria-pressed': String(app.filter === f[0]), 'data-filter': f[0],
        on: { click: function () { app.filter = f[0]; T.tap(); render(false); } }
      }, f[1], h('span', { class: 'count' }, count));
    })));
    fill();
    append(view, listBox);
    append(view, fab());
    return view;
  }

  // A record: everything about it and what can be done with it.
  function cardScreen(id) {
    var r = record(id);
    var view = h('main', { class: 'view' }, inPageBack());
    if (!r) {
      append(view, h('section', { class: 'card' }, h('div', { class: 'empty' },
        h('strong', null, 'Запись не найдена'), 'Возможно, её удалили на сайте.')));
      return view;
    }
    var facts = [['Тип', KIND_NAMES[r.kind]]];
    var every = period(r.cycle, r.frequency);
    facts.push(['Повторяется', every || 'не повторяется']);
    facts.push(['Дата', when(r)]);
    if (r.price > 0) {
      var price = amount(r.price, symbolOf(r.currency));
      if (r.monthly !== null && !(r.cycle === 3 && r.frequency === 1)) price += ' · ≈ ' + amount(r.monthly, symbolOf(r.currency)) + ' в месяц';
      facts.push(['Сумма', price]);
    }
    if (r.category && r.category.name) facts.push(['Категория', r.category.name]);
    facts.push(['Напоминания', reminderText(r, app.state.account.reminder_days)]);
    if (every && r.auto_renew) facts.push(['Автопродление', 'включено']);

    append(view, h('section', { class: 'card' },
      h('div', { class: 'record-head' },
        h('span', { class: 'status ' + r.status }, h('span', { class: 'dot ' + r.status }), STATUS_NAMES[r.status]),
        h('h1', null, r.name)),
      h('dl', { class: 'facts' }, facts.map(function (f) {
        return h('div', { class: 'fact' }, h('dt', null, f[0]), h('dd', null, f[1]));
      }))));

    var actions = h('section', { class: 'actions' });
    if (r.next_payment) {
      if (r.inactive) {
        append(actions, actionButton('↩️ Вернуть в работу', 'btn', function () { act(r, 'reactivate'); }));
      } else {
        append(actions, actionButton('✅ Продлить на ' + renewPeriod(r.cycle, r.frequency), 'btn', function () { act(r, 'renew'); }));
        if (r.notify && r.days_left !== null && r.days_left <= 7) {
          append(actions, actionButton('⏰ Напомнить завтра', 'btn secondary', function () { act(r, 'snooze'); }));
        }
      }
    }
    append(actions, actionButton('✏️ Изменить', 'btn secondary', function () { openForm(r.id); }));
    if (r.next_payment && !r.inactive) {
      append(actions, actionButton('❌ Отменить', 'btn secondary', function () {
        confirmSheet('Отменить «' + r.name + '»?', 'Напоминания по этой записи перестанут приходить. Вернуть её можно в любой момент.', 'Отменить запись')
          .then(function (ok) { if (ok) act(r, 'cancel'); });
      }));
    }
    append(actions, actionButton('🗑 Удалить', 'btn danger', function () {
      confirmSheet('Удалить «' + r.name + '»?',
        'Запись исчезнет и на сайте, напоминаний по ней больше не будет. Это действие нельзя отменить.', 'Удалить')
        .then(function (ok) { if (ok) act(r, 'delete'); });
    }));
    append(view, actions);
    return view;
  }

  function actionButton(label, cls, handler) {
    return h('button', { class: cls, type: 'button', disabled: app.busy, on: { click: handler } }, label);
  }

  var OUTCOMES = {
    renew: function (r) { return r ? 'Продлено. Следующая дата — ' + formatDate(r.next_payment) + '.' : 'Продлено.'; },
    cancel: function () { return 'Отменено. Напоминаний по этой записи больше не будет.'; },
    snooze: function () { return 'Хорошо, напомню завтра.'; },
    reactivate: function () { return 'Запись снова активна, напоминания вернутся.'; },
    delete: function () { return 'Запись удалена.'; }
  };
  var REFUSALS = {
    stale: 'Запись уже изменилась — показана актуальная.',
    inactive: 'Запись уже отменена.',
    active: 'Запись уже активна.',
    not_recurring: 'Эту запись нельзя продлить. Измените дату.',
    not_found: 'Запись не найдена — возможно, её удалили на сайте.'
  };

  function act(r, action) {
    if (app.busy) return;
    mutate('act', { id: r.id, action: action, expected_due: r.next_payment }, function (data) {
      if (data.status === 'done') {
        T.haptic('success');
        toast(OUTCOMES[action](record(r.id)));
        if (action === 'delete' || !record(r.id)) back();
        return;
      }
      T.haptic('warning');
      toast(REFUSALS[data.status] || 'Не получилось. Попробуйте ещё раз.', true);
      if (!record(r.id)) back();
    });
  }

  // A change: sent with one request id, so "Повторить" after a lost answer is safe.
  function mutate(op, body, done, requestId) {
    requestId = requestId || newRequestId();
    app.busy = true;
    mainBusy(true);
    render(false);
    return api(op, body, requestId).then(function (data) {
      app.busy = false;
      mainBusy(false);
      if (data.status === 'not_linked') { app.phase = 'not_linked'; app.stack = []; render(true); return; }
      if (data.state) app.state = data.state;
      render(false);
      done(data);
    }, function (err) {
      app.busy = false;
      mainBusy(false);
      render(false);
      T.haptic('error');
      if (err.kind === 'network') {
        confirmSheet('Нет связи с сервером', 'Изменение могло не дойти. Повторить? Повтор не применит его дважды.', 'Повторить')
          .then(function (again) { if (again) mutate(op, body, done, requestId); });
      } else if (err.kind === 'unauthorized') {
        app.error = err; app.phase = 'error'; render(true);
      } else {
        toast('Сервер не смог выполнить действие. Попробуйте ещё раз.', true);
      }
    });
  }

  // --- the form ------------------------------------------------------------------------------

  var CYCLES = [
    ['5-1', 'Не повторяется'], ['1-1', 'Каждый день'], ['2-1', 'Каждую неделю'], ['3-1', 'Каждый месяц'],
    ['3-3', 'Каждые 3 месяца'], ['3-6', 'Каждые 6 месяцев'], ['4-1', 'Каждый год'], ['custom', 'Другой период…']
  ];
  var DEFAULT_CYCLE = { subscription: '3-1', expiry: '5-1', maintenance: '3-1' };
  var UNITS = [[1, 'дней'], [2, 'недель'], [3, 'месяцев'], [4, 'лет']];
  var REMIND = [0, 1, 2, 3, 5, 7, 14, 30];
  var FIELD_NAMES = {
    name: 'name', price: 'price', currency_id: 'price', next_payment: 'next_payment',
    cycle: 'cycle', frequency: 'cycle', category_id: 'category_id', notify_days_before: 'notify_days_before', kind: 'kind'
  };
  var SERVER_ERRORS = {
    name: 'Укажите название.',
    price: 'Укажите сумму — число не меньше нуля.',
    currency_id: 'Выберите валюту из списка.',
    next_payment: 'Укажите дату.',
    cycle: 'Проверьте, как часто повторяется запись.',
    frequency: 'Укажите период от 1 до 366.',
    category_id: 'Такой категории больше нет — выберите другую.',
    notify_days_before: 'Проверьте срок напоминания.',
    kind: 'Выберите тип записи.'
  };

  function openForm(id) {
    var r = id ? record(id) : null;
    var main = mainCurrency();
    var noCategory = app.state.categories.filter(function (c) { return !c.name; })[0];
    var cycleKey = r ? r.cycle + '-' + r.frequency : DEFAULT_CYCLE.subscription;
    var known = CYCLES.some(function (c) { return c[0] === cycleKey; });
    app.form = {
      id: r ? r.id : null,
      kind: r ? r.kind : 'subscription',
      name: r ? r.name : '',
      price: r && r.price > 0 ? String(r.price).replace('.', ',') : '',
      currency_id: r && r.currency ? r.currency.id : (main ? main.id : null),
      next_payment: r ? r.next_payment || '' : '',
      cycle: r && r.cycle === 5 ? '5-1' : (known ? cycleKey : 'custom'),
      custom_unit: r && r.cycle !== 5 ? r.cycle : 3,
      custom_every: r ? r.frequency : 2,
      category_id: r && r.category ? r.category.id : (noCategory ? noCategory.id : null),
      notify: r ? r.notify : true,
      notify_days_before: r && r.notify_days_before !== null ? r.notify_days_before : -1,
      auto_renew: r ? !!r.auto_renew : false,
      cycle_touched: !!r,
      dirty: false,
      errors: {},
      message: null
    };
    go({ name: 'form', id: id || null });
  }

  function cycleValue(f) {
    if (f.cycle === 'custom') return [Number(f.custom_unit), Number(f.custom_every)];
    var p = f.cycle.split('-');
    return [Number(p[0]), Number(p[1])];
  }

  function validate(f) {
    var errors = {};
    if (!f.name.trim()) errors.name = 'Укажите название.';
    else if (f.name.trim().length > 255) errors.name = 'Название длиннее 255 символов.';
    var price = f.price.trim().replace(/\s/g, '');
    if (price === '') {
      if (f.kind === 'subscription') errors.price = 'У подписки должна быть сумма.';
    } else if (!/^\d+([.,]\d{1,2})?$/.test(price)) {
      errors.price = 'Сумма — число, например 500 или 9,99.';
    }
    if (!f.currency_id) errors.price = errors.price || 'Выберите валюту.';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(f.next_payment)) errors.next_payment = 'Укажите дату.';
    if (f.cycle === 'custom') {
      var every = Number(f.custom_every);
      if (!Number.isInteger(every) || every < 1 || every > 366) errors.cycle = 'Период — целое число от 1 до 366.';
    }
    return errors;
  }

  function payload(f) {
    var cycle = cycleValue(f);
    var out = {
      kind: f.kind,
      name: f.name.trim(),
      price: f.price.trim().replace(/\s/g, '').replace(',', '.'),
      currency_id: Number(f.currency_id),
      next_payment: f.next_payment,
      cycle: cycle[0],
      frequency: cycle[0] === 5 ? 1 : cycle[1],
      category_id: f.category_id === null ? null : Number(f.category_id),
      notify: !!f.notify,
      notify_days_before: Number(f.notify_days_before),
      auto_renew: cycle[0] !== 5 && !!f.auto_renew
    };
    if (f.id) out.id = f.id;
    return out;
  }

  function save() {
    var f = app.form;
    if (!f || app.busy) return;
    f.errors = validate(f);
    f.message = null;
    if (Object.keys(f.errors).length) {
      T.haptic('error');
      render(false);
      focusFirstError();
      return;
    }
    mutate('save', { record: payload(f) }, function (data) {
      if (data.status === 'saved') {
        T.haptic('success');
        var created = !f.id;
        app.form = null;
        app.stack.pop();
        if (created) app.stack.push({ name: 'card', id: data.id });
        toast(created ? 'Запись добавлена.' : 'Изменения сохранены.');
        render(true);
        return;
      }
      if (data.status === 'not_found') {
        app.form = null;
        app.stack = [];
        toast('Запись не найдена — возможно, её удалили на сайте.', true);
        render(true);
        return;
      }
      // Refused by the website's validation: show it at the field.
      var field = FIELD_NAMES[data.field] || null;
      f.errors = {};
      if (field) f.errors[field] = SERVER_ERRORS[data.field] || 'Проверьте это поле.';
      else f.message = 'Не удалось сохранить. Проверьте данные.';
      T.haptic('error');
      render(false);
      focusFirstError();
    });
  }

  function focusFirstError() {
    var el = root.querySelector('.field.invalid input, .field.invalid select, .form-error');
    if (el) {
      el.scrollIntoView({ block: 'center' });
      if (el.focus) el.focus();
    }
  }

  function bindFormButton() {
    var f = app.form;
    setMain(f.id ? 'Сохранить' : 'Добавить запись', save);
    if (app.busy) mainBusy(true);
    T.closingConfirmation(f.dirty);
  }

  function formScreen() {
    var f = app.form;
    if (!f) return h('main', { class: 'view' });
    var s = app.state;

    function change(key, value, rerender) {
      f[key] = value;
      if (!f.dirty) { f.dirty = true; T.closingConfirmation(true); }
      if (f.errors[key]) { delete f.errors[key]; rerender = true; }
      if (rerender) render(false);
    }

    function field(key, label, control, hint) {
      var error = f.errors[key];
      return h('label', { class: 'field' + (error ? ' invalid' : '') },
        h('span', { class: 'field-label' }, label), control,
        error ? h('span', { class: 'field-error', role: 'alert' }, error) : (hint ? h('span', { class: 'field-hint' }, hint) : null));
    }

    var cycle = cycleValue(f);
    var recurring = cycle[0] !== 5;
    var kinds = [['subscription', 'Подписка'], ['expiry', 'Срок'], ['maintenance', 'Обслуживание']];
    var dueLabel = { subscription: 'Следующий платёж', expiry: 'Годен до', maintenance: 'Следующее обслуживание' }[f.kind];

    var view = h('main', { class: 'view' }, inPageBack(),
      h('h1', { class: 'page-title' }, f.id ? 'Изменить запись' : 'Новая запись'));
    if (f.message) append(view, h('p', { class: 'form-error', role: 'alert', tabindex: '-1' }, f.message));

    append(view, h('section', { class: 'card' },
      h('div', { class: 'field' },
        h('span', { class: 'field-label', id: 'kind-label' }, 'Что отслеживаем'),
        h('div', { class: 'segmented', role: 'group', 'aria-labelledby': 'kind-label' }, kinds.map(function (k) {
          return h('button', {
            type: 'button', 'aria-pressed': String(f.kind === k[0]), 'data-kind': k[0],
            on: {
              click: function () {
                if (!f.cycle_touched) f.cycle = DEFAULT_CYCLE[k[0]];
                T.tap();
                change('kind', k[0], true);
              }
            }
          }, k[1]);
        }))),
      field('name', 'Название', h('input', {
        type: 'text', name: 'name', value: f.name, maxlength: '255', autocomplete: 'off',
        placeholder: { subscription: 'Например, Spotify', expiry: 'Например, Молоко', maintenance: 'Например, Фильтр для воды' }[f.kind],
        on: { input: function (e) { change('name', e.target.value); } }
      })),
      field('next_payment', dueLabel, h('input', {
        type: 'date', name: 'next_payment', value: f.next_payment,
        on: { change: function (e) { change('next_payment', e.target.value); } }
      })),
      field('price', f.kind === 'subscription' ? 'Сумма платежа' : 'Сумма (если есть)', h('div', { class: 'split' },
        h('input', {
          type: 'text', name: 'price', inputmode: 'decimal', value: f.price, placeholder: '0', autocomplete: 'off',
          on: { input: function (e) { change('price', e.target.value); } }
        }),
        h('select', {
          name: 'currency_id', 'aria-label': 'Валюта', value: String(f.currency_id),
          on: { change: function (e) { change('currency_id', Number(e.target.value)); } }
        }, s.currencies.map(function (c) {
          return h('option', { value: String(c.id) }, c.code + (c.symbol && c.symbol !== c.code ? ' ' + c.symbol : ''));
        })))),
      field('cycle', 'Повторяется', h('div', null,
        h('select', {
          name: 'cycle', value: f.cycle,
          on: { change: function (e) { f.cycle_touched = true; change('cycle', e.target.value, true); } }
        }, CYCLES.map(function (c) { return h('option', { value: c[0] }, c[1]); })),
        f.cycle === 'custom' ? h('div', { class: 'split even' },
          h('input', {
            type: 'number', name: 'custom_every', min: '1', max: '366', inputmode: 'numeric', value: String(f.custom_every),
            'aria-label': 'Каждые', on: { input: function (e) { change('custom_every', e.target.value); } }
          }),
          h('select', {
            name: 'custom_unit', 'aria-label': 'Единица', value: String(f.custom_unit),
            on: { change: function (e) { change('custom_unit', Number(e.target.value)); } }
          }, UNITS.map(function (u) { return h('option', { value: String(u[0]) }, u[1]); }))) : null)),
      categoryField(f, field, change)));

    var defaultDays = s.account.reminder_days;
    var remind = REMIND.slice();
    if (f.notify_days_before >= 0 && remind.indexOf(Number(f.notify_days_before)) === -1) remind.push(Number(f.notify_days_before));
    remind.sort(function (a, b) { return a - b; });

    append(view, h('h2', { class: 'section-title' }, 'Напоминания'));
    append(view, h('section', { class: 'card' },
      switchRow('notify', 'Напоминать', 'Заранее, в том числе сюда, в Telegram', f.notify, function (on) { change('notify', on, true); }),
      f.notify ? field('notify_days_before', 'Когда', h('select', {
        name: 'notify_days_before', value: String(f.notify_days_before),
        on: { change: function (e) { change('notify_days_before', Number(e.target.value)); } }
      }, [h('option', { value: '-1' }, 'По умолчанию — ' + (defaultDays === 0 ? 'в день даты' : 'за ' + days(defaultDays)))].concat(
        remind.map(function (d) { return h('option', { value: String(d) }, d === 0 ? 'В день даты' : 'За ' + days(d)); })))) : null,
      recurring ? switchRow('auto_renew', 'Продлевать автоматически', 'Когда дата пройдёт, она сама перейдёт на следующий период', f.auto_renew,
        function (on) { change('auto_renew', on); }) : null));

    if (!tg || !tg.MainButton) {
      append(view, h('div', { class: 'actions' }, actionButton(f.id ? 'Сохранить' : 'Добавить запись', 'btn', save)));
    }
    return view;
  }

  function categoryField(f, field, change) {
    var named = app.state.categories.filter(function (c) { return c.name; });
    if (!named.length) return null;
    var none = app.state.categories.filter(function (c) { return !c.name; })[0];
    var options = [h('option', { value: none ? String(none.id) : '' }, 'Без категории')].concat(named.map(function (c) {
      return h('option', { value: String(c.id) }, c.name);
    }));
    return field('category_id', 'Категория', h('select', {
      name: 'category_id', value: f.category_id === null ? '' : String(f.category_id),
      on: { change: function (e) { change('category_id', e.target.value === '' ? null : Number(e.target.value)); } }
    }, options));
  }

  function switchRow(name, title, hint, checked, onChange) {
    var input = h('input', {
      type: 'checkbox', role: 'switch', name: name, checked: checked,
      on: { change: function () { T.tap(); onChange(input.checked); } }
    });
    return h('label', { class: 'switch' }, h('span', { class: 'switch-text' }, title, hint ? h('small', null, hint) : null), input);
  }

  // --- soon, spending, settings ---------------------------------------------------------------

  function soonScreen() {
    var s = app.state;
    var view = h('main', { class: 'view' },
      h('h1', { class: 'page-title' }, 'Скоро'),
      h('p', { class: 'page-subtitle' }, 'Ближайшие 30 дней'));
    if (!s.upcoming.groups.length) {
      append(view, h('section', { class: 'card' }, h('div', { class: 'empty' },
        h('strong', null, 'Ничего не запланировано'), 'В ближайшие 30 дней нет ни платежей, ни сроков.')));
    }
    s.upcoming.groups.forEach(function (g) {
      var items = g.records.map(function (r) { return record(r.id); }).filter(Boolean);
      if (!items.length) return;
      append(view, h('h2', { class: 'section-title' }, GROUP_TITLES[g.key] || g.key));
      append(view, h('section', { class: 'card' }, h('ul', { class: 'list' }, items.map(function (r) { return recordRow(r); }))));
    });
    if (s.upcoming.later) {
      append(view, h('p', { class: 'note' }, 'Позже: ещё ' + s.upcoming.later + ' ' + plural(s.upcoming.later, 'запись', 'записи', 'записей') + '. ',
        h('button', { class: 'link-button', type: 'button', on: { click: function () { switchTab('records'); } } }, 'Все записи ›')));
    }
    return view;
  }

  function spendScreen() {
    var s = app.state;
    var e = s.expenses;
    var view = h('main', { class: 'view' },
      h('h1', { class: 'page-title' }, 'Расходы'),
      h('p', { class: 'page-subtitle' }, 'Активные подписки'));
    if (!e.per_currency.length && !e.due_30_days.length) {
      append(view, h('section', { class: 'card' }, h('div', { class: 'empty' },
        h('strong', null, 'Пока нечего считать'),
        'Добавьте подписку с суммой — здесь появятся расходы в месяц и ближайшие платежи.')));
      return view;
    }

    if (e.per_currency.length) {
      var month = e.per_currency.map(function (m) {
        return h('div', { class: 'money-line' },
          h('span', { class: 'label' }, m.count + ' ' + plural(m.count, 'подписка', 'подписки', 'подписок')),
          h('span', { class: 'amount' }, amount(m.monthly, symbolOf(m.currency))));
      });
      if (e.per_currency.length > 1) {
        if (e.total) {
          month.push(h('div', { class: 'money-line' }, h('span', { class: 'label' }, 'Итого'),
            h('span', { class: 'amount' }, '≈ ' + amount(e.total.monthly, symbolOf(e.total.currency)))));
        }
      }
      append(view, h('h2', { class: 'section-title' }, 'В месяц'), h('section', { class: 'card card-body' }, month));
      if (e.per_currency.length > 1) {
        append(view, h('p', { class: 'note' }, e.total
          ? (e.total.rates_date ? 'Итого — по курсам на ' + formatDate(e.total.rates_date) + '.' : 'Итого — по курсам с сайта.')
          : 'Суммы в разных валютах не складываются: на сайте не загружены курсы валют.'));
      }
      var yearly = e.per_currency.map(function (m) { return amount(m.monthly * 12, symbolOf(m.currency)); }).join(' + ');
      append(view, h('p', { class: 'note' }, 'В год ≈ ' + yearly));
    }

    if (e.top.length) {
      append(view, h('h2', { class: 'section-title' }, 'Самые дорогие'));
      append(view, h('section', { class: 'card' }, h('ul', { class: 'list' }, e.top.map(function (t) {
        var r = record(t.id);
        return r ? recordRow(r, amount(t.monthly, symbolOf(t.currency)) + ' / мес') : null;
      }))));
    }

    if (e.by_category.length && e.by_category.some(function (c) { return c.name; })) {
      var main = mainCurrency();
      var scope = e.convertible && e.total ? e.total.currency : main;
      var total = e.by_category.reduce(function (acc, c) { return acc + c.monthly; }, 0) || 1;
      var title = 'По категориям';
      if (e.category_scope === 'main' && e.per_currency.length > 1 && scope) title += ' (только ' + scope.code + ')';
      append(view, h('h2', { class: 'section-title' }, title));
      append(view, h('section', { class: 'card card-body' }, e.by_category.slice(0, 8).map(function (c) {
        var share = Math.round(c.monthly * 100 / total);
        var bar = h('i');
        bar.style.width = Math.max(2, share) + '%';
        return h('div', { class: 'category-line' },
          h('div', { class: 'money-line' },
            h('span', null, c.name || 'Без категории'),
            h('span', { class: 'amount' }, amount(c.monthly, symbolOf(scope)), h('span', { class: 'label' }, ' · ' + share + '%'))),
          h('div', { class: 'bar' }, bar));
      })));
    }

    if (e.due_30_days.length) {
      append(view, h('h2', { class: 'section-title' }, 'К оплате за 30 дней'));
      append(view, h('section', { class: 'card card-body' }, e.due_30_days.map(function (m) {
        return h('div', { class: 'money-line' },
          h('span', { class: 'label' }, m.count + ' ' + plural(m.count, 'платёж', 'платежа', 'платежей')),
          h('span', { class: 'amount' }, amount(m.amount, symbolOf(m.currency))));
      })));
    }

    append(view, h('p', { class: 'note' },
      'В месяц: недельные платежи ×4,35, годовые ÷12 — как в статистике на сайте. Разовые покупки и отменённые подписки не учитываются.'));
    return view;
  }

  function settingsScreen() {
    var s = app.state;
    var d = s.account.reminder_days;
    var view = h('main', { class: 'view' }, h('h1', { class: 'page-title' }, 'Настройки'));

    append(view, h('section', { class: 'card' }, h('dl', { class: 'facts' },
      h('div', { class: 'fact' }, h('dt', null, 'Аккаунт'), h('dd', null, s.account.username)),
      h('div', { class: 'fact' }, h('dt', null, 'Telegram'), h('dd', null, 'привязан')))));

    append(view, h('h2', { class: 'section-title' }, 'Напоминать по умолчанию'));
    var options = [];
    for (var i = 0; i <= 7; i++) options.push(i);
    append(view, h('section', { class: 'card card-body' },
      h('div', { class: 'days', role: 'group', 'aria-label': 'За сколько дней напоминать' }, options.map(function (n) {
        return h('button', {
          type: 'button', 'aria-pressed': String(n === d), 'data-days': n, disabled: app.busy,
          'aria-label': n === 0 ? 'В день даты' : 'За ' + days(n),
          on: { click: function () { if (n !== d) saveReminderDays(n); } }
        }, n === 0 ? 'в день' : n + ' дн.');
      })),
      h('p', { class: 'field-hint' }, d === 0 ? 'Сейчас: в день даты.' : 'Сейчас: за ' + days(d) + ' до даты.')));
    append(view, h('p', { class: 'note' },
      'Для записей, где не указан свой срок. Это та же настройка, что на сайте в разделе «Уведомления». Время рассылки задаётся на сервере.'));

    append(view, h('div', { class: 'actions' },
      h('button', { class: 'btn secondary', type: 'button', on: { click: function () { T.openLink(location.origin + '/'); } } }, 'Открыть сайт'),
      h('button', { class: 'btn danger', type: 'button', disabled: app.busy, on: { click: unlink } }, 'Отвязать Telegram')));
    return view;
  }

  function saveReminderDays(n) {
    T.tap();
    mutate('settings', { reminder_days: n }, function (data) {
      if (data.status === 'saved') {
        T.haptic('success');
        toast('Сохранено: напоминать ' + (n === 0 ? 'в день даты' : 'за ' + days(n)) + '.');
      } else {
        toast('Такое значение нельзя выбрать.', true);
      }
    });
  }

  function unlink() {
    confirmSheet('Отвязать Telegram?',
      'Напоминания перестанут приходить в Telegram, а бот и приложение больше не увидят ваши записи. Сами записи останутся на сайте.',
      'Отвязать').then(function (ok) {
      if (!ok) return;
      mutate('unlink', { confirm: true }, function (data) {
        if (data.status === 'unlinked') {
          T.haptic('success');
          app.state = null;
          app.stack = [];
          app.phase = 'unlinked';
          render(true);
        } else {
          toast('Не получилось отвязать. Попробуйте ещё раз.', true);
        }
      });
    });
  }

  // --- states without an account -----------------------------------------------------------

  function stateView(title, children) {
    return h('main', { class: 'view' }, h('section', { class: 'state' }, logoMark(), h('h1', null, title), children));
  }

  function outsideScreen() {
    var link = botUsername ? 'https://t.me/' + botUsername : null;
    return stateView('Откройте ShelfLife в Telegram', [
      h('p', null, 'Это приложение работает внутри Telegram: так ShelfLife узнаёт вас без пароля.'),
      link ? h('div', { class: 'actions' }, h('a', { class: 'btn', href: link, rel: 'noopener' }, 'Открыть бота @' + botUsername)) : null,
      h('p', null, h('a', { href: '../', class: 'link-button' }, 'Перейти на сайт ShelfLife'))
    ]);
  }

  function notLinkedScreen() {
    return stateView('Аккаунт ещё не привязан', [
      h('p', null, 'ShelfLife не знает этот Telegram. Привяжите его к аккаунту на сайте — это займёт минуту:'),
      h('ol', null,
        h('li', null, 'Войдите на сайт ShelfLife.'),
        h('li', null, 'Откройте «Профиль → Telegram-бот».'),
        h('li', null, 'Нажмите «Привязать Telegram» и перейдите по ссылке.')),
      h('div', { class: 'actions' },
        h('button', { class: 'btn', type: 'button', on: { click: function () { T.openLink(location.origin + '/'); } } }, 'Открыть сайт'),
        h('button', { class: 'btn secondary', type: 'button', on: { click: load } }, 'Проверить ещё раз'))
    ]);
  }

  function unlinkedScreen() {
    return stateView('Telegram отвязан', [
      h('p', null, 'Напоминания сюда больше не придут. Записи остались на сайте.'),
      h('p', null, 'Чтобы привязать снова: на сайте «Профиль → Telegram-бот» → «Привязать Telegram».'),
      h('div', { class: 'actions' }, h('button', { class: 'btn secondary', type: 'button', on: { click: T.close } }, 'Закрыть'))
    ]);
  }

  function errorScreen() {
    var err = app.error || {};
    var title = 'Что-то пошло не так';
    var text = 'Сервер не ответил как нужно. Попробуйте ещё раз.';
    var retry = true;
    if (err.kind === 'network') {
      title = 'Нет связи с сервером';
      text = 'Проверьте интернет и попробуйте ещё раз.';
    } else if (err.kind === 'unauthorized') {
      retry = false;
      title = err.reason === 'expired' ? 'Сессия устарела' : 'Telegram не подтвердил вход';
      text = 'Закройте приложение и откройте его снова из бота.';
    } else if (err.kind === 'not_configured') {
      retry = false;
      title = 'Приложение не настроено';
      text = 'На сервере ShelfLife не указан токен бота. Обратитесь к администратору.';
    }
    return stateView(title, [
      h('p', null, text),
      h('div', { class: 'actions' }, retry
        ? h('button', { class: 'btn', type: 'button', on: { click: load } }, 'Повторить')
        : h('button', { class: 'btn secondary', type: 'button', on: { click: T.close } }, 'Закрыть'))
    ]);
  }

  // --- start ---------------------------------------------------------------------------------

  function load() {
    app.phase = 'loading';
    render(true);
    return api('state').then(function (data) {
      if (data.status === 'not_linked') { app.phase = 'not_linked'; render(true); return; }
      if (data.status !== 'ok' || !data.state) throw new ApiError('server');
      app.state = data.state;
      app.phase = 'ready';
      openRequestedScreen();
      render(true);
    }).catch(function (err) {
      app.error = err instanceof ApiError ? err : new ApiError('server');
      app.phase = 'error';
      render(true);
    });
  }

  // The bot's "✏️ Изменить в приложении" opens index.php?edit=<id>.
  var requested = (function () {
    var m = /[?&]edit=(\d{1,10})(?:&|$)/.exec(location.search);
    return m ? Number(m[1]) : null;
  })();

  function openRequestedScreen() {
    if (requested === null) return;
    var id = requested;
    requested = null;
    if (!record(id)) { toast('Запись не найдена — возможно, её удалили на сайте.', true); return; }
    app.tab = 'records';
    app.stack = [{ name: 'card', id: id }];
    openForm(id);
  }

  function start() {
    if (tg) {
      try {
        tg.ready();
        tg.expand();
        if (tg.BackButton && T.atLeast('6.1')) tg.BackButton.onClick(onBack);
        if (tg.MainButton) tg.MainButton.onClick(onMain);
        tg.onEvent('themeChanged', applyTheme);
      } catch (e) { /* an old client: the page still works */ }
      applyTheme();
    }
    if (!T.inside) {
      app.phase = 'outside';
      render(true);
      return;
    }
    load();
  }

  // For the UI check (scripts/tma_ui_check.py): the formatting the bot shares.
  window.ShelfLifeFormat = { amount: amount, relativeDays: relativeDays, period: period, renewPeriod: renewPeriod, plural: plural };

  start();
})();
