<?php
/*
  ShelfLife Telegram Mini App API (called by tma/app.js).

  The caller is identified only by the X-Telegram-Init-Data header, verified
  against the bot's token (includes/shelflife/webapp_auth.php): no session
  cookie, no Telegram id taken from the request. A Telegram account that is not
  linked to a ShelfLife account gets {"status": "not_linked"} and nothing else.
  The operations are in includes/shelflife/webapp_api.php.
*/

require_once __DIR__ . '/../../includes/instance_config.php';
require_once __DIR__ . '/../../includes/shelflife/webapp_auth.php';
require_once __DIR__ . '/../../includes/shelflife/webapp_api.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function shelflife_tma_respond($status, array $body)
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    shelflife_tma_respond(405, ['status' => 'method_not_allowed']);
}

$token = wallos_env_secret('TELEGRAM_BOT_TOKEN')['value'] ?? null;
if (!is_string($token) || $token === '') {
    shelflife_tma_respond(503, ['status' => 'not_configured']);
}

$auth = shelflife_webapp_verify($_SERVER['HTTP_X_TELEGRAM_INIT_DATA'] ?? '', $token, time());
if (!$auth['ok']) {
    shelflife_tma_respond(401, ['status' => 'unauthorized', 'reason' => $auth['reason']]);
}

$request = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($request)) {
    shelflife_tma_respond(400, ['status' => 'invalid_json']);
}

$db = new SQLite3(__DIR__ . '/../../db/wallos.db');
$db->busyTimeout(5000);

$user = shelflife_link_find_user($db, $auth['user']['id']);
if ($user === null) {
    $db->close();
    $botUsername = (string) (wallos_env_value('TELEGRAM_BOT_USERNAME') ?? '');
    shelflife_tma_respond(200, ['status' => 'not_linked', 'bot_username' => preg_match('/^[A-Za-z0-9_]{5,32}$/', $botUsername) ? $botUsername : null]);
}

try {
    $response = shelflife_webapp_handle($db, $user, $auth['user']['id'], $request, shelflife_today());
} catch (Throwable $e) {
    error_log('ShelfLife Mini App: ' . $e->getMessage());
    $db->close();
    shelflife_tma_respond(500, ['status' => 'error']);
}
$db->close();

shelflife_tma_respond(200, $response);
