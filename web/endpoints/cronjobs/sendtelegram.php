<?php
/*
  ShelfLife: plans and sends reminders through the ShelfLife Telegram bot.
  Scheduled every 5 minutes in cronjobs; see includes/shelflife/notifications.php.

  - New reminders are planned only from SHELFLIFE_NOTIFY_HOUR (default 9) in the
    application's time zone, so nobody is woken up at night; retries of earlier
    reminders go out at any time.
  - An exclusive lock keeps two runs from overlapping.
  - Without TELEGRAM_BOT_TOKEN (or TELEGRAM_BOT_TOKEN_FILE) it does nothing.
*/

require_once 'validate.php';
require_once __DIR__ . '/../../includes/connect_endpoint_crontabs.php';
require_once __DIR__ . '/../../includes/instance_config.php';
require_once __DIR__ . '/../../includes/shelflife/notifications.php';
require_once __DIR__ . '/../../includes/shelflife/telegram_api.php';

require 'settimezone.php';

$lock = fopen(sys_get_temp_dir() . '/shelflife-sendtelegram.lock', 'c');
if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
    echo date('Y-m-d H:i:s') . " another run is in progress\n";
    exit;
}

$token = wallos_env_secret('TELEGRAM_BOT_TOKEN')['value'] ?? null;
if (!is_string($token) || $token === '') {
    echo date('Y-m-d H:i:s') . " TELEGRAM_BOT_TOKEN is not set; Telegram reminders are off\n";
    exit;
}

$notifyHour = wallos_env_value('SHELFLIFE_NOTIFY_HOUR');
$notifyHour = is_numeric($notifyHour) ? max(0, min(23, (int) $notifyHour)) : 9;
$localHour = (int) (new DateTimeImmutable('now', shelflife_timezone()))->format('G');

$counts = shelflife_notify_run(
    $db,
    shelflife_telegram_sender($token),
    shelflife_today(),
    time(),
    200,
    fn() => usleep(50000),
    $localHour >= $notifyHour
);

echo date('Y-m-d H:i:s') . ' ' . json_encode($counts) . "\n";

flock($lock, LOCK_UN);
$db->close();
