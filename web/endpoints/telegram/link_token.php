<?php
/*
  ShelfLife: issues a one-time token for linking the signed-in account to the
  Telegram bot and returns it as a t.me deep link (shown on the profile page as
  a link and a QR code). See includes/shelflife/telegram_link.php.
*/

require_once '../../includes/connect_endpoint.php';
require_once '../../includes/validate_endpoint.php';
require_once '../../includes/instance_config.php';
require_once '../../includes/shelflife/telegram_link.php';

header('Content-Type: application/json');
header('Cache-Control: no-store');

$botUsername = trim((string) wallos_env_value('TELEGRAM_BOT_USERNAME'));
$botUsername = ltrim($botUsername, '@');
if (!preg_match('/^[A-Za-z][A-Za-z0-9_]{3,31}$/', $botUsername)) {
    echo json_encode(['success' => false, 'message' => translate('telegram_bot_not_configured', $i18n)]);
    exit;
}

try {
    $issued = shelflife_link_issue_token($db, $userId, time());
} catch (RuntimeException $e) {
    error_log('ShelfLife: ' . $e->getMessage());
    echo json_encode(['success' => false, 'message' => translate('error', $i18n)]);
    exit;
}

echo json_encode([
    'success' => true,
    'token' => $issued['token'],
    'link' => 'https://t.me/' . $botUsername . '?start=' . $issued['token'],
    'expires_in' => SHELFLIFE_LINK_TOKEN_TTL,
]);
