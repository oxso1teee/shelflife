<?php
/*
  ShelfLife internal API: a notification button pressed in Telegram.

  Request:  {"telegram_id": 123, "update_id": 456, "subscription_id": 7,
             "action": "renew"|"cancel"|"snooze"|"reactivate"|"delete", "expected_due": "2026-11-15", "snooze_days": 1}
  Response: {"status": "done"|"stale"|"inactive"|"active"|"not_recurring", "action": "...", "record": {...}}
          | {"status": "done", "action": "delete", "record": null}
          | {"status": "not_found"} | {"status": "invalid"} | {"status": "not_linked"}

  "stale" means the record no longer has the due date the button was sent for:
  it was already renewed, changed on the website or pressed twice.

  A repeated update_id answers the first response again ("repeated": true), but
  only to the Telegram account it was first processed for; another account gets
  {"status": "invalid"} and nothing else.
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/bot_actions.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');
$updateId = shelflife_internal_int($payload, 'update_id');
shelflife_internal_int($payload, 'subscription_id');

$db = shelflife_internal_db();
$user = shelflife_link_find_user($db, $telegramId);
if ($user === null) {
    $db->close();
    shelflife_internal_respond(200, ['status' => 'not_linked']);
}

$response = shelflife_bot_once($db, $updateId, $telegramId, fn() => shelflife_bot_act($db, $user, $payload, shelflife_today()));
$db->close();

shelflife_internal_respond(200, $response);
