<?php
/*
  ShelfLife internal API: everything the bot shows of the linked account —
  records, what is due soon, spending, categories, currencies, settings — from
  includes/shelflife/overview.php, the same computation the Mini App uses.

  Request:  {"telegram_id": 123}
  Response: {"status": "linked", "overview": {...}, "site_url": "https://..." | null}
          | {"status": "not_linked"}
*/

require_once __DIR__ . '/../../../includes/shelflife/internal_api.php';
require_once __DIR__ . '/../../../includes/shelflife/telegram_link.php';
require_once __DIR__ . '/../../../includes/shelflife/overview.php';
require_once __DIR__ . '/../../../includes/instance_config.php';

$payload = shelflife_internal_request();
$telegramId = shelflife_internal_int($payload, 'telegram_id');

$db = shelflife_internal_db();
$user = shelflife_link_find_user($db, $telegramId);
if ($user === null) {
    $db->close();
    shelflife_internal_respond(200, ['status' => 'not_linked']);
}

$overview = shelflife_overview($db, (int) $user['id'], shelflife_today());
$siteUrl = trim((string) (wallos_get_admin_settings($db)['server_url'] ?? ''));
$db->close();

shelflife_internal_respond(200, [
    'status' => 'linked',
    'overview' => $overview,
    'site_url' => preg_match('#^https://[^\s/]+#', $siteUrl) ? rtrim($siteUrl, '/') : null,
]);
