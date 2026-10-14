<?php
/*
  ShelfLife: reminders through the Telegram bot, one message per record, with
  "renewed", "cancelled" and "remind me later" buttons.

  Run every few minutes by endpoints/cronjobs/sendtelegram.php:

  1. Plan. For every active record of a linked account with reminders on, the
     reminder day is the due date minus the record's "days before" (or the
     account default), or the snooze date if that is later. Once that day has
     come, a row is added to telegram_outbox. The row is unique per record, due
     date and reminder day, so planning again changes nothing, and a reminder
     day missed while the server was down is still sent on the next run.
  2. Send. Rows are claimed one at a time (pending -> sending), so two runs
     cannot send the same row. The record is read again first; a reminder for a
     due date that has since been renewed, cancelled or edited is dropped. The
     text is written at sending time from the days left, so a late message does
     not say "tomorrow" about yesterday.
  3. Telegram's answer decides what happens next: sent; flood control (429)
     retries after the time Telegram asks for; a blocked bot (403) or a rejected
     message (400) is not retried; network and server errors are retried with a
     growing delay, up to SHELFLIFE_NOTIFY_MAX_ATTEMPTS.

  Delivery is at least once: a crash between Telegram accepting a message and
  the row being marked sent can repeat that one message.
*/

require_once __DIR__ . '/dates.php';
require_once __DIR__ . '/subscription_service.php';
require_once __DIR__ . '/status.php';

const SHELFLIFE_NOTIFY_MAX_ATTEMPTS = 5;
const SHELFLIFE_NOTIFY_STALE_LOCK_SECONDS = 600;
// Records more than this many days overdue are not announced any more, so
// linking an old account does not bring a flood of stale reminders.
const SHELFLIFE_NOTIFY_OVERDUE_GRACE_DAYS = 3;
const SHELFLIFE_NOTIFY_DEFAULT_DAYS = 1;

/**
 * Queues the reminders that are due by $today.
 *
 * @param string $today Y-m-d in the application's time zone
 * @param int    $now   unix time
 * @return int number of new reminders queued
 */
function shelflife_notify_plan(SQLite3 $db, $today, $now)
{
    $oldest = (new DateTimeImmutable($today, new DateTimeZone('UTC')))
        ->modify('-' . SHELFLIFE_NOTIFY_OVERDUE_GRACE_DAYS . ' days')->format('Y-m-d');

    $select = $db->prepare("SELECT s.id, s.user_id, s.next_payment, s.notify_days_before, s.snoozed_until,
                                   (SELECT ns.days FROM notification_settings ns WHERE ns.user_id = s.user_id LIMIT 1) AS default_days
                            FROM subscriptions s
                            JOIN user u ON u.id = s.user_id
                            WHERE u.telegram_id IS NOT NULL AND s.notify = 1 AND s.inactive = 0
                              AND s.next_payment >= :oldest");
    $select->bindValue(':oldest', $oldest, SQLITE3_TEXT);
    $result = $select->execute();

    $insert = $db->prepare("INSERT OR IGNORE INTO telegram_outbox
                                (user_id, subscription_id, due_date, remind_on, status, attempts, next_attempt_at, created_at)
                            VALUES (:userId, :subscriptionId, :due, :remindOn, 'pending', 0, :now, :now)");

    $queued = 0;
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        if (!shelflife_is_valid_date($row['next_payment'])) {
            continue;
        }

        $daysBefore = $row['notify_days_before'];
        if ($daysBefore === null || (int) $daysBefore < 0) {
            $daysBefore = $row['default_days'] === null ? SHELFLIFE_NOTIFY_DEFAULT_DAYS : max(0, (int) $row['default_days']);
        }

        $remindOn = (new DateTimeImmutable($row['next_payment'], new DateTimeZone('UTC')))
            ->modify('-' . (int) $daysBefore . ' days')->format('Y-m-d');
        if (shelflife_is_valid_date($row['snoozed_until']) && $row['snoozed_until'] > $remindOn) {
            $remindOn = $row['snoozed_until'];
        }

        if ($remindOn > $today) {
            continue;
        }

        $insert->bindValue(':userId', (int) $row['user_id'], SQLITE3_INTEGER);
        $insert->bindValue(':subscriptionId', (int) $row['id'], SQLITE3_INTEGER);
        $insert->bindValue(':due', $row['next_payment'], SQLITE3_TEXT);
        $insert->bindValue(':remindOn', $remindOn, SQLITE3_TEXT);
        $insert->bindValue(':now', (int) $now, SQLITE3_INTEGER);
        $insert->execute();
        $queued += $db->changes();
        $insert->reset();
    }

    return $queued;
}

/**
 * Takes the next pending reminder for sending, or returns null when there is
 * none. Reminders stuck in "sending" (a crashed run) are put back first.
 *
 * @return array|null the outbox row
 */
function shelflife_notify_claim(SQLite3 $db, $now)
{
    $release = $db->prepare("UPDATE telegram_outbox SET status = 'pending', locked_at = NULL
                             WHERE status = 'sending' AND locked_at < :stale");
    $release->bindValue(':stale', (int) $now - SHELFLIFE_NOTIFY_STALE_LOCK_SECONDS, SQLITE3_INTEGER);
    $release->execute();

    $next = $db->prepare("SELECT * FROM telegram_outbox WHERE status = 'pending' AND next_attempt_at <= :now
                          ORDER BY next_attempt_at, id LIMIT 1");
    $next->bindValue(':now', (int) $now, SQLITE3_INTEGER);
    $row = $next->execute()->fetchArray(SQLITE3_ASSOC);
    if ($row === false) {
        return null;
    }

    $claim = $db->prepare("UPDATE telegram_outbox SET status = 'sending', locked_at = :now WHERE id = :id AND status = 'pending'");
    $claim->bindValue(':now', (int) $now, SQLITE3_INTEGER);
    $claim->bindValue(':id', (int) $row['id'], SQLITE3_INTEGER);
    $claim->execute();
    if ($db->changes() !== 1) {
        // Another run took it first; try the next one.
        return shelflife_notify_claim($db, $now);
    }

    $row['status'] = 'sending';

    return $row;
}

function shelflife_notify_finish(SQLite3 $db, $id, $status, array $fields = [])
{
    $assignments = ['status = :status', 'locked_at = NULL'];
    foreach (array_keys($fields) as $column) {
        $assignments[] = $column . ' = :' . $column;
    }

    $stmt = $db->prepare('UPDATE telegram_outbox SET ' . implode(', ', $assignments) . ' WHERE id = :id');
    $stmt->bindValue(':status', $status, SQLITE3_TEXT);
    foreach ($fields as $column => $value) {
        $stmt->bindValue(':' . $column, $value, $value === null ? SQLITE3_NULL : (is_int($value) ? SQLITE3_INTEGER : SQLITE3_TEXT));
    }
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->execute();
}

function shelflife_notify_price($price, $symbol)
{
    $formatted = number_format((float) $price, 2, ',', ' ');
    $formatted = preg_replace('/,00$/', '', $formatted);

    return $formatted . ' ' . $symbol;
}

/**
 * The reminder text and its buttons.
 *
 * @param array       $record         the subscriptions row
 * @param string|null $currencySymbol symbol of the record's currency
 * @param string      $today          Y-m-d
 * @return array{text: string, reply_markup: array}
 */
function shelflife_notify_message(array $record, $currencySymbol, $today)
{
    $name = htmlspecialchars(html_entity_decode((string) $record['name'], ENT_QUOTES, 'UTF-8'), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    $due = $record['next_payment'];
    $daysLeft = shelflife_days_between($today, $due);
    $dateText = (new DateTimeImmutable($due, new DateTimeZone('UTC')))->format('d.m.Y');
    $kind = $record['kind'] ?? SHELFLIFE_KIND_SUBSCRIPTION;

    if ($daysLeft > 1) {
        $when = 'через ' . shelflife_ru_days($daysLeft);
    } elseif ($daysLeft === 1) {
        $when = 'завтра';
    } elseif ($daysLeft === 0) {
        $when = 'сегодня';
    } else {
        $when = null;
    }

    switch ($kind) {
        case SHELFLIFE_KIND_EXPIRY:
            $text = $when === null
                ? "Срок годности <b>$name</b> истёк " . shelflife_ru_days($daysLeft) . " назад ($dateText)."
                : "Срок годности <b>$name</b> истекает $when ($dateText).";
            break;
        case SHELFLIFE_KIND_MAINTENANCE:
            $text = $when === null
                ? "Обслуживание <b>$name</b> просрочено на " . shelflife_ru_days($daysLeft) . " ($dateText)."
                : 'Обслуживание <b>' . $name . '</b> — ' . $when . " ($dateText).";
            break;
        default:
            $price = (float) $record['price'] > 0 ? ' (' . htmlspecialchars(shelflife_notify_price($record['price'], (string) $currencySymbol), ENT_QUOTES, 'UTF-8') . ')' : '';
            $text = $when === null
                ? "Оплата за <b>$name</b>$price была " . shelflife_ru_days($daysLeft) . " назад ($dateText)."
                : shelflife_ucfirst($when) . " спишется оплата за <b>$name</b>$price — $dateText.";
    }

    $renewLabel = ((int) $record['cycle'] === SHELFLIFE_CYCLE_MONTHS && (int) $record['frequency'] === 1) || (int) $record['cycle'] === SHELFLIFE_CYCLE_ONE_TIME
        ? 'Продлено на месяц'
        : 'Продлено';

    // Read by the bot as CallbackData(prefix="a"): record id, due date, action.
    $data = fn($action) => 'a:' . (int) $record['id'] . ':' . str_replace('-', '', $due) . ':' . $action;

    return [
        'text' => $text,
        'reply_markup' => [
            'inline_keyboard' => [
                [['text' => $renewLabel, 'callback_data' => $data('r')]],
                [
                    ['text' => 'Отменено', 'callback_data' => $data('c')],
                    ['text' => 'Напомнить позже', 'callback_data' => $data('s')],
                ],
            ],
        ],
    ];
}

function shelflife_ucfirst($text)
{
    return mb_strtoupper(mb_substr($text, 0, 1, 'UTF-8'), 'UTF-8') . mb_substr($text, 1, null, 'UTF-8');
}

/**
 * Sends one claimed reminder and records the outcome.
 *
 * @param callable $send fn($chatId, $text, $replyMarkup) => answer of shelflife_telegram_call()
 * @return string the outbox status afterwards
 */
function shelflife_notify_deliver(SQLite3 $db, array $row, callable $send, $today, $now)
{
    $record = shelflife_subscription_find($db, $row['user_id'], $row['subscription_id']);
    if ($record === null || (int) $record['inactive'] === 1 || (int) $record['notify'] !== 1 || $record['next_payment'] !== $row['due_date']) {
        shelflife_notify_finish($db, $row['id'], 'cancelled', ['last_error' => 'record changed before sending']);
        return 'cancelled';
    }

    $user = $db->prepare('SELECT telegram_id FROM user WHERE id = :id');
    $user->bindValue(':id', (int) $row['user_id'], SQLITE3_INTEGER);
    $userRow = $user->execute()->fetchArray(SQLITE3_ASSOC);
    if ($userRow === false || $userRow['telegram_id'] === null) {
        shelflife_notify_finish($db, $row['id'], 'cancelled', ['last_error' => 'Telegram unlinked']);
        return 'cancelled';
    }

    $symbol = $db->prepare('SELECT symbol FROM currencies WHERE id = :id');
    $symbol->bindValue(':id', (int) $record['currency_id'], SQLITE3_INTEGER);
    $currency = $symbol->execute()->fetchArray(SQLITE3_ASSOC);

    $message = shelflife_notify_message($record, $currency === false ? '' : $currency['symbol'], $today);
    $answer = $send((int) $userRow['telegram_id'], $message['text'], $message['reply_markup']);

    if ($answer['ok']) {
        shelflife_notify_finish($db, $row['id'], 'sent', [
            'sent_at' => (int) $now,
            'telegram_message_id' => isset($answer['result']['message_id']) ? (int) $answer['result']['message_id'] : null,
            'last_error' => null,
        ]);
        return 'sent';
    }

    $attempts = (int) $row['attempts'] + 1;
    $error = $answer['network_error'] ?? trim(($answer['error_code'] ?? '') . ' ' . ($answer['description'] ?? ''));

    if ($answer['error_code'] === 429) {
        // Flood control is not the message's fault and does not count as an attempt.
        shelflife_notify_finish($db, $row['id'], 'pending', [
            'next_attempt_at' => (int) $now + max(1, (int) ($answer['retry_after'] ?? 30)),
            'last_error' => $error,
        ]);
        return 'pending';
    }

    if (in_array($answer['error_code'], [400, 403], true) || $attempts >= SHELFLIFE_NOTIFY_MAX_ATTEMPTS) {
        // 403: the user blocked the bot or deleted the chat; 400: Telegram refused the message.
        shelflife_notify_finish($db, $row['id'], 'failed', ['attempts' => $attempts, 'last_error' => $error]);
        return 'failed';
    }

    shelflife_notify_finish($db, $row['id'], 'pending', [
        'attempts' => $attempts,
        'next_attempt_at' => (int) $now + 60 * (2 ** ($attempts - 1)),
        'last_error' => $error,
    ]);
    return 'pending';
}

/**
 * One run: plan, then send everything due now.
 *
 * @param callable $send     see shelflife_notify_deliver()
 * @param callable $pause    fn(): void between messages (Telegram allows ~30 messages a second)
 * @param bool     $plan     false before the notification hour: only retries are sent
 * @return array counts by outcome
 */
function shelflife_notify_run(SQLite3 $db, callable $send, $today, $now, $sendLimit = 200, $pause = null, $plan = true)
{
    $counts = ['queued' => $plan ? shelflife_notify_plan($db, $today, $now) : 0, 'sent' => 0, 'pending' => 0, 'failed' => 0, 'cancelled' => 0];

    for ($i = 0; $i < $sendLimit; $i++) {
        $row = shelflife_notify_claim($db, $now);
        if ($row === null) {
            break;
        }

        $counts[shelflife_notify_deliver($db, $row, $send, $today, $now)]++;
        if ($pause !== null) {
            $pause();
        }
    }

    return $counts;
}
