<?php
/*
  ShelfLife internal API: the settings the bot can change for the linked account.

  Request:  {"telegram_id": 123, "update_id": 456, "op": "reminder_days", "days": 0..7}
          | {"telegram_id": 123, "update_id": 456, "op": "unlink"}
  Response: {"status": "saved", "reminder_days": 2} | {"status": "unlinked"}
          | {"status": "invalid", "field": "...", "message": "..."} | {"status": "not_linked"}

  "reminder_days" is the account's notification setting on the website (days
  before the due date for records set to "default"). "unlink" removes the link
  to Telegram, as the profile page does; linking again needs a new link from
  the website. A repeated update_id is answered once (shelflife_bot_once()).
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/bot_actions.php';
require_once __DIR__ . '/../../../includes/shelflife/overview.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');
$updateId = shelflife_internal_int($payload, 'update_id');

$db = shelflife_internal_db();
$user = shelflife_link_find_user($db, $telegramId);
if ($user === null) {
    $db->close();
    shelflife_internal_respond(200, ['status' => 'not_linked']);
}

$response = shelflife_bot_once($db, $updateId, $telegramId, function () use ($db, $user, $payload) {
    switch ($payload['op'] ?? null) {
        case 'reminder_days':
            try {
                return ['status' => 'saved', 'reminder_days' => shelflife_set_reminder_days($db, (int) $user['id'], $payload['days'] ?? null)];
            } catch (ShelfLifeValidationError $e) {
                return ['status' => 'invalid', 'field' => $e->field, 'message' => $e->getMessage()];
            }
        case 'unlink':
            shelflife_link_unlink($db, (int) $user['id']);
            return ['status' => 'unlinked'];
        default:
            return ['status' => 'invalid', 'field' => 'op', 'message' => 'Unknown operation.'];
    }
});
$db->close();

shelflife_internal_respond(200, $response);
