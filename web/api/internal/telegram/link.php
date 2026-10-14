<?php
/*
  ShelfLife internal API: link the account a /start token was issued for to the
  Telegram user who sent it.

  Request:  {"token": "<32 hex>", "telegram_id": 123, "telegram_username": "name" | null}
  Response: {"status": "linked" | "invalid_token" | "telegram_taken", "username": "<wallos username>" | null}
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/telegram_link.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');

$token = $payload['token'] ?? null;
$telegramUsername = $payload['telegram_username'] ?? null;
if (!is_string($telegramUsername) || !preg_match('/^[A-Za-z0-9_]{1,64}$/', $telegramUsername)) {
    $telegramUsername = null;
}

$db = shelflife_internal_db();
$result = shelflife_link_consume($db, $token, $telegramId, $telegramUsername, time());
$db->close();

shelflife_internal_respond(200, ['status' => $result['status'], 'username' => $result['username']]);
