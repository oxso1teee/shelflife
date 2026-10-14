<?php
/*
  ShelfLife internal API: create a record from the bot's /add command.

  Request:  {"telegram_id": 123, "update_id": 456, "kind": "subscription"|"expiry"|"maintenance",
             "name": "Spotify", "next_payment": "2026-11-15",
             "price": "500" (optional for expiry/maintenance), "currency": "RUB" (optional, ISO code),
             "cycle": 1..5 (optional), "frequency": 1.. (optional)}
  Response: {"status": "created", "record": {...}}
          | {"status": "invalid", "field": "...", "message": "..."}
          | {"status": "not_linked"}
  A repeated update_id answers the first response again ("repeated": true), but
  only to the Telegram account it was first processed for; another account gets
  {"status": "invalid"} and nothing else.
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/bot_actions.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');
$updateId = shelflife_internal_int($payload, 'update_id');

$db = shelflife_internal_db();
$user = shelflife_link_find_user($db, $telegramId);
if ($user === null) {
    $db->close();
    shelflife_internal_respond(200, ['status' => 'not_linked']);
}

$response = shelflife_bot_once($db, $updateId, $telegramId, fn() => shelflife_bot_add_record($db, $user, $payload, shelflife_today()));
$db->close();

shelflife_internal_respond(200, $response);
