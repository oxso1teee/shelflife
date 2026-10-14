<?php
/*
  ShelfLife: what the Telegram bot can do to a linked account's records.

  Called by the internal API (api/internal/telegram/item_add.php, item_action.php)
  on behalf of the Telegram user the bot names. Every change goes through the
  same service as the web form (subscription_service.php), so validation,
  ownership checks and date rules are the ones the website applies.
*/

require_once __DIR__ . '/subscription_service.php';
require_once __DIR__ . '/telegram_link.php';

const SHELFLIFE_BOT_ACTIONS = ['renew', 'cancel', 'snooze'];

/**
 * Runs $action once per Telegram update. A repeated update id gets the response
 * stored the first time; the record change and the stored response are
 * committed together.
 *
 * The stored response names the record it acted on, so it goes back only to the
 * Telegram account it was stored for. Telegram never gives two accounts the same
 * update id: the same id from another account is refused as "invalid", without
 * the stored response and without running $action.
 *
 * @param callable $action fn(): array
 * @return array
 */
function shelflife_bot_once(SQLite3 $db, $updateId, $telegramId, callable $action)
{
    $db->exec('BEGIN IMMEDIATE');
    try {
        $seen = $db->prepare('SELECT telegram_id, response FROM telegram_processed_updates WHERE update_id = :id');
        $seen->bindValue(':id', (int) $updateId, SQLITE3_INTEGER);
        $row = $seen->execute()->fetchArray(SQLITE3_ASSOC);
        if ($row !== false) {
            $db->exec('COMMIT');
            if ((int) $row['telegram_id'] !== (int) $telegramId) {
                error_log('ShelfLife: Telegram update ' . (int) $updateId . ' was already processed for another account; refused');
                return ['status' => 'invalid'];
            }
            return json_decode($row['response'], true) + ['repeated' => true];
        }

        $response = $action();

        $store = $db->prepare('INSERT INTO telegram_processed_updates (update_id, telegram_id, response, created_at)
                               VALUES (:id, :telegramId, :response, :now)');
        $store->bindValue(':id', (int) $updateId, SQLITE3_INTEGER);
        $store->bindValue(':telegramId', (int) $telegramId, SQLITE3_INTEGER);
        $store->bindValue(':response', json_encode($response), SQLITE3_TEXT);
        $store->bindValue(':now', time(), SQLITE3_INTEGER);
        if ($store->execute() === false) {
            throw new RuntimeException('Failed to record the update: ' . $db->lastErrorMsg());
        }

        $purge = $db->prepare('DELETE FROM telegram_processed_updates WHERE created_at < :before');
        $purge->bindValue(':before', time() - 2 * 86400, SQLITE3_INTEGER);
        $purge->execute();

        $db->exec('COMMIT');
    } catch (Throwable $e) {
        $db->exec('ROLLBACK');
        throw $e;
    }

    return $response;
}

/**
 * The record as the bot shows it. Wallos stores names HTML-escaped; the bot
 * escapes for Telegram itself, so it gets the plain text.
 */
function shelflife_bot_record_view(array $row, $currencyCode = null)
{
    return [
        'id' => (int) $row['id'],
        'kind' => $row['kind'] ?? SHELFLIFE_KIND_SUBSCRIPTION,
        'name' => html_entity_decode((string) $row['name'], ENT_QUOTES, 'UTF-8'),
        'next_payment' => $row['next_payment'],
        'price' => (float) $row['price'],
        'currency' => $currencyCode,
        'cycle' => (int) $row['cycle'],
        'frequency' => (int) $row['frequency'],
        'inactive' => (int) $row['inactive'] === 1,
        'snoozed_until' => $row['snoozed_until'] ?? null,
    ];
}

function shelflife_bot_currency_code(SQLite3 $db, $currencyId)
{
    $stmt = $db->prepare('SELECT code FROM currencies WHERE id = :id');
    $stmt->bindValue(':id', (int) $currencyId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return $row === false ? null : $row['code'];
}

/**
 * The user's currency with ISO code $code, or the user's main currency when no
 * code is given.
 *
 * @return int|null null when the user has no currency with that code
 */
function shelflife_bot_currency_id(SQLite3 $db, array $user, $code)
{
    if ($code === null || $code === '') {
        return (int) $user['main_currency'];
    }

    $stmt = $db->prepare('SELECT id FROM currencies WHERE user_id = :userId AND UPPER(code) = :code ORDER BY id LIMIT 1');
    $stmt->bindValue(':userId', (int) $user['id'], SQLITE3_INTEGER);
    $stmt->bindValue(':code', strtoupper((string) $code), SQLITE3_TEXT);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return $row === false ? null : (int) $row['id'];
}

/**
 * The first of the user's categories, household members or payment methods —
 * what the web form preselects.
 *
 * @return int|null
 */
function shelflife_bot_default_id(SQLite3 $db, $table, $userId)
{
    $queries = [
        'categories' => 'SELECT id FROM categories WHERE user_id = :userId ORDER BY "order", id LIMIT 1',
        'household' => 'SELECT id FROM household WHERE user_id = :userId ORDER BY id LIMIT 1',
        'payment_methods' => 'SELECT id FROM payment_methods WHERE user_id = :userId AND enabled = 1 ORDER BY "order", id LIMIT 1',
    ];

    $stmt = $db->prepare($queries[$table]);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return $row === false ? null : (int) $row['id'];
}

/**
 * Creates a record from the bot's /add command.
 *
 * @param array  $user    the linked account (shelflife_link_find_user())
 * @param array  $payload kind, name, next_payment, and optionally price, currency, cycle, frequency
 * @param string $today   Y-m-d
 * @return array ['status' => 'created', 'record' => [...]] | ['status' => 'invalid', 'field' => ..., 'message' => ...]
 */
function shelflife_bot_add_record(SQLite3 $db, array $user, array $payload, $today)
{
    $kind = $payload['kind'] ?? SHELFLIFE_KIND_SUBSCRIPTION;
    $defaultCycles = [
        SHELFLIFE_KIND_SUBSCRIPTION => SHELFLIFE_CYCLE_MONTHS,
        SHELFLIFE_KIND_EXPIRY => SHELFLIFE_CYCLE_ONE_TIME,
        SHELFLIFE_KIND_MAINTENANCE => SHELFLIFE_CYCLE_MONTHS,
    ];

    $currencyId = shelflife_bot_currency_id($db, $user, $payload['currency'] ?? null);
    if ($currencyId === null) {
        return ['status' => 'invalid', 'field' => 'currency', 'message' => 'unknown_currency'];
    }

    $userId = (int) $user['id'];
    $input = [
        'kind' => $kind,
        'name' => is_string($payload['name'] ?? null) ? $payload['name'] : '',
        'price' => $payload['price'] ?? null,
        'currency_id' => $currencyId,
        'cycle' => $payload['cycle'] ?? ($defaultCycles[$kind] ?? SHELFLIFE_CYCLE_MONTHS),
        'frequency' => $payload['frequency'] ?? 1,
        'next_payment' => $payload['next_payment'] ?? null,
        'start_date' => $today,
        'auto_renew' => false,
        'category_id' => shelflife_bot_default_id($db, 'categories', $userId),
        'payer_user_id' => shelflife_bot_default_id($db, 'household', $userId),
        'payment_method_id' => shelflife_bot_default_id($db, 'payment_methods', $userId),
        'notify' => true,
        'notify_days_before' => -1,
    ];
    // Values from Telegram are numbers or strings; the service wants strings or ints.
    foreach (['price', 'cycle', 'frequency'] as $field) {
        if (is_float($input[$field])) {
            $input[$field] = (string) $input[$field];
        }
    }

    try {
        $data = shelflife_subscription_prepare($db, $userId, $input);
        $id = shelflife_subscription_insert($db, $userId, $data);
    } catch (ShelfLifeValidationError $e) {
        return ['status' => 'invalid', 'field' => $e->field, 'message' => $e->getMessage()];
    }

    $row = shelflife_subscription_find($db, $userId, $id);

    return ['status' => 'created', 'record' => shelflife_bot_record_view($row, shelflife_bot_currency_code($db, $row['currency_id']))];
}

/**
 * Applies a notification button to the user's record.
 *
 * @param array  $payload subscription_id, action (renew|cancel|snooze), expected_due, optional snooze_days
 * @param string $today   Y-m-d
 * @return array status plus the record as it is afterwards
 */
function shelflife_bot_act(SQLite3 $db, array $user, array $payload, $today)
{
    $userId = (int) $user['id'];
    $id = (int) ($payload['subscription_id'] ?? 0);
    $action = $payload['action'] ?? null;
    $expectedDue = $payload['expected_due'] ?? null;

    if (!in_array($action, SHELFLIFE_BOT_ACTIONS, true) || !shelflife_is_valid_date($expectedDue)) {
        return ['status' => 'invalid'];
    }

    switch ($action) {
        case 'renew':
            $result = shelflife_subscription_renew($db, $userId, $id, $today, $expectedDue, true);
            break;
        case 'cancel':
            $result = shelflife_subscription_cancel($db, $userId, $id, $today, $expectedDue);
            break;
        default:
            $days = (int) ($payload['snooze_days'] ?? 1);
            $result = shelflife_subscription_snooze($db, $userId, $id, $today, $expectedDue, min(30, max(1, $days)));
    }

    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found'];
    }

    $statusByAction = ['renew' => 'renewed', 'cancel' => 'cancelled', 'snooze' => 'snoozed'];

    return [
        'status' => $result['status'] === $statusByAction[$action] ? 'done' : $result['status'],
        'action' => $action,
        'record' => shelflife_bot_record_view($row, shelflife_bot_currency_code($db, $row['currency_id'])),
    ];
}
