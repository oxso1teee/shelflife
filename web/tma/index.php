<?php
/*
  ShelfLife Telegram Mini App: the page Telegram opens (menu button, "Открыть
  приложение" in the bot). It is a static shell — no session, no account data:
  app.js asks api/tma/app.php for everything, signed with the init data
  Telegram gives the page, and the server checks that signature with the bot
  token before it answers (includes/shelflife/webapp_auth.php).

  Opened outside Telegram, the page has no init data and says where to open it.
*/

require_once __DIR__ . '/../includes/version.php';
require_once __DIR__ . '/../includes/instance_config.php';

$botUsername = (string) (wallos_env_value('TELEGRAM_BOT_USERNAME') ?? '');
if (!preg_match('/^[A-Za-z0-9_]{5,32}$/', $botUsername)) {
    $botUsername = '';
}

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-cache');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
// Scripts only from this site and Telegram's Mini App library; data only from this site.
header("Content-Security-Policy: default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'");
?>
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <meta name="robots" content="noindex">
  <title>ShelfLife</title>
  <link rel="icon" href="../images/icon/favicon-32x32.png" sizes="32x32">
  <link rel="stylesheet" href="app.css?<?= htmlspecialchars($assetVersion) ?>">
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
</head>
<body>
  <div id="app" data-bot="<?= htmlspecialchars($botUsername) ?>" aria-live="polite">
    <div class="boot" role="status">
      <svg class="boot-mark" viewBox="0 0 100 100" aria-hidden="true">
        <path d="M13 8H53A9 9 0 0 1 53 26H13A9 9 0 0 1 13 8ZM13 41H35A9 9 0 0 1 35 59H13A9 9 0 0 1 13 41ZM13 74H17A9 9 0 0 1 17 92H13A9 9 0 0 1 13 74Z" class="mark-bars"/>
        <path d="M46 70A26 26 0 1 1 98 70A26 26 0 1 1 46 70ZM68.5 56A3.5 3.5 0 0 1 75.5 56L75.5 66.5L83 66.5A3.5 3.5 0 0 1 83 73.5L72 73.5A3.5 3.5 0 0 1 68.5 70Z" fill-rule="evenodd" class="mark-clock"/>
      </svg>
      <span>Загрузка…</span>
    </div>
  </div>
  <noscript><p class="noscript">Для ShelfLife нужен JavaScript.</p></noscript>
  <script src="app.js?<?= htmlspecialchars($assetVersion) ?>"></script>
</body>
</html>
