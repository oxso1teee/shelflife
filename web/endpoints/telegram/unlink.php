<?php
/*
  ShelfLife: unlinks the signed-in account from Telegram and voids its unused
  link tokens. The bot stops sending notifications to that Telegram account.
*/

require_once '../../includes/connect_endpoint.php';
require_once '../../includes/validate_endpoint.php';
require_once '../../includes/shelflife/telegram_link.php';

header('Content-Type: application/json');

shelflife_link_unlink($db, $userId);

echo json_encode(['success' => true, 'message' => translate('success', $i18n)]);
