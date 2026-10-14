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
require_once __DIR__ . '/../default_names.php';

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

/**
 * "1 500 ₽", "9,99 $" (no-break spaces); just the amount without a symbol.
 */
function shelflife_notify_price($price, $symbol)
{
    $formatted = number_format((float) $price, 2, ',', "\u{00A0}");
    $formatted = preg_replace('/,00$/', '', $formatted);

    return $symbol === '' ? $formatted : $formatted . "\u{00A0}" . $symbol;
}

/**
 * Russian plural form: 1 месяц, 2 месяца, 5 месяцев.
 */
function shelflife_ru_plural($n, $one, $few, $many)
{
    $n = abs((int) $n);
    $mod10 = $n % 10;
    $mod100 = $n % 100;
    if ($mod10 === 1 && $mod100 !== 11) {
        return $one;
    }
    if ($mod10 >= 2 && $mod10 <= 4 && ($mod100 < 12 || $mod100 > 14)) {
        return $few;
    }

    return $many;
}

/**
 * "каждый месяц", "каждые 3 месяца"; null for a one-time record.
 */
function shelflife_notify_period($cycle, $frequency)
{
    $units = [
        SHELFLIFE_CYCLE_DAYS => ['каждый день', 'день', 'дня', 'дней'],
        SHELFLIFE_CYCLE_WEEKS => ['каждую неделю', 'неделю', 'недели', 'недель'],
        SHELFLIFE_CYCLE_MONTHS => ['каждый месяц', 'месяц', 'месяца', 'месяцев'],
        SHELFLIFE_CYCLE_YEARS => ['каждый год', 'год', 'года', 'лет'],
    ];
    $unit = $units[(int) $cycle] ?? null;
    if ($unit === null) {
        return null;
    }
    $n = max(1, (int) $frequency);

    return $n === 1 ? $unit[0] : 'каждые ' . $n . ' ' . shelflife_ru_plural($n, $unit[1], $unit[2], $unit[3]);
}

/**
 * The "renewed" button names the period it renews for. A one-time record is
 * moved by a month (shelflife_subscription_renew() with $allowOneTime).
 */
function shelflife_notify_renew_label($cycle, $frequency)
{
    $units = [
        SHELFLIFE_CYCLE_DAYS => ['день', 'дня', 'дней'],
        SHELFLIFE_CYCLE_WEEKS => ['неделю', 'недели', 'недель'],
        SHELFLIFE_CYCLE_MONTHS => ['месяц', 'месяца', 'месяцев'],
        SHELFLIFE_CYCLE_YEARS => ['год', 'года', 'лет'],
    ];
    $unit = $units[(int) $cycle] ?? null;
    $n = max(1, (int) $frequency);
    if ($unit === null || $n === 1) {
        return 'Продлено на ' . ($unit === null ? 'месяц' : $unit[0]);
    }

    return 'Продлено на ' . $n . ' ' . shelflife_ru_plural($n, $unit[0], $unit[1], $unit[2]);
}

/**
 * Plain text cut to $max characters with an ellipsis.
 */
function shelflife_notify_shorten($text, $max)
{
    $text = trim((string) $text);

    return mb_strlen($text, 'UTF-8') > $max ? rtrim(mb_substr($text, 0, $max - 1, 'UTF-8')) . '…' : $text;
}

/**
 * The record's category for the reminder, or null when it has none: the
 * account's "no category" (in its language or Wallos's English default).
 */
function shelflife_notify_category(SQLite3 $db, array $record, $language)
{
    if (empty($record['category_id'])) {
        return null;
    }
    $stmt = $db->prepare('SELECT name FROM categories WHERE id = :id AND user_id = :userId');
    $stmt->bindValue(':id', (int) $record['category_id'], SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $record['user_id'], SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($row === false) {
        return null;
    }
    $name = trim(html_entity_decode((string) $row['name'], ENT_QUOTES, 'UTF-8'));
    if ($name === '' || in_array($name, [default_no_category_name((string) $language), 'No category'], true)) {
        return null;
    }

    return $name;
}

const SHELFLIFE_NOTIFY_KIND_NAMES = [
    SHELFLIFE_KIND_SUBSCRIPTION => 'Подписка',
    SHELFLIFE_KIND_EXPIRY => 'Срок годности',
    SHELFLIFE_KIND_MAINTENANCE => 'Обслуживание',
];

/**
 * The reminder text and its buttons. The same card as the bot's /add answer:
 *
 *   🔔 Оплата завтра
 *
 *   <b>Spotify</b>
 *   Подписка · каждый месяц · Развлечения
 *   Дата: 15.11.2026
 *   Сумма: 500 ₽
 *
 * @param array       $record         the subscriptions row
 * @param string|null $currencySymbol symbol of the record's currency
 * @param string      $today          Y-m-d
 * @param string|null $category       the record's category, plain text; null for none
 * @return array{text: string, reply_markup: array}
 */
function shelflife_notify_message(array $record, $currencySymbol, $today, $category = null)
{
    $escape = fn($text) => htmlspecialchars($text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    $name = $escape(shelflife_notify_shorten(html_entity_decode((string) $record['name'], ENT_QUOTES, 'UTF-8'), 80));
    $due = $record['next_payment'];
    $daysLeft = shelflife_days_between($today, $due);
    $kind = $record['kind'] ?? SHELFLIFE_KIND_SUBSCRIPTION;
    $cycle = (int) ($record['cycle'] ?? SHELFLIFE_CYCLE_MONTHS);

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
            $headline = $when === null ? 'Срок годности истёк ' . shelflife_ru_days($daysLeft) . ' назад' : 'Срок годности истекает ' . $when;
            break;
        case SHELFLIFE_KIND_MAINTENANCE:
            $headline = $when === null ? 'Обслуживание просрочено на ' . shelflife_ru_days($daysLeft) : 'Обслуживание ' . $when;
            break;
        default:
            $kind = SHELFLIFE_KIND_SUBSCRIPTION;
            $headline = $when === null ? 'Оплата просрочена на ' . shelflife_ru_days($daysLeft) : 'Оплата ' . $when;
    }

    $details = [SHELFLIFE_NOTIFY_KIND_NAMES[$kind]];
    $period = shelflife_notify_period($cycle, $record['frequency'] ?? 1);
    if ($period !== null) {
        $details[] = $period;
    } elseif ($kind === SHELFLIFE_KIND_SUBSCRIPTION) {
        $details[] = 'разово';
    }
    if (is_string($category) && trim($category) !== '') {
        $details[] = $escape(shelflife_notify_shorten($category, 40));
    }

    $lines = [
        ($when === null ? '⚠️ ' : '🔔 ') . $headline,
        '',
        '<b>' . $name . '</b>',
        implode(' · ', $details),
        'Дата: ' . (new DateTimeImmutable($due, new DateTimeZone('UTC')))->format('d.m.Y'),
    ];
    if ((float) ($record['price'] ?? 0) > 0) {
        $lines[] = 'Сумма: ' . $escape(shelflife_notify_price($record['price'], (string) $currencySymbol));
    }

    // Read by the bot as CallbackData(prefix="a"): record id, due date, action.
    $data = fn($action) => 'a:' . (int) $record['id'] . ':' . str_replace('-', '', $due) . ':' . $action;

    return [
        'text' => implode("\n", $lines),
        'reply_markup' => [
            'inline_keyboard' => [
                [['text' => shelflife_notify_renew_label($cycle, $record['frequency'] ?? 1), 'callback_data' => $data('r')]],
                [
                    ['text' => 'Отменено', 'callback_data' => $data('c')],
                    ['text' => 'Напомнить позже', 'callback_data' => $data('s')],
                ],
            ],
        ],
    ];
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

    $user = $db->prepare('SELECT telegram_id, language FROM user WHERE id = :id');
    $user->bindValue(':id', (int) $row['user_id'], SQLITE3_INTEGER);
    $userRow = $user->execute()->fetchArray(SQLITE3_ASSOC);
    if ($userRow === false || $userRow['telegram_id'] === null) {
        shelflife_notify_finish($db, $row['id'], 'cancelled', ['last_error' => 'Telegram unlinked']);
        return 'cancelled';
    }

    $symbol = $db->prepare('SELECT symbol FROM currencies WHERE id = :id');
    $symbol->bindValue(':id', (int) $record['currency_id'], SQLITE3_INTEGER);
    $currency = $symbol->execute()->fetchArray(SQLITE3_ASSOC);

    $category = shelflife_notify_category($db, $record, $userRow['language'] ?? 'en');
    $message = shelflife_notify_message($record, $currency === false ? '' : $currency['symbol'], $today, $category);
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
