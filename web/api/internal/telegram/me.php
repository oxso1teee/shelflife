<?php
/*
  ShelfLife internal API: which account, if any, a Telegram user is linked to.

  Request:  {"telegram_id": 123}
  Response: {"linked": true, "username": "<wallos username>"} | {"linked": false, "username": null}
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/telegram_link.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');

$db = shelflife_internal_db();
$user = shelflife_link_find_user($db, $telegramId);
$db->close();

shelflife_internal_respond(200, ['linked' => $user !== null, 'username' => $user['username'] ?? null]);
