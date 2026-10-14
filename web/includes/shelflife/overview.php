<?php
/*
  ShelfLife: what Telegram (the bot and the Mini App) shows of an account —
  its records, what is due soon, spending and settings — computed here once,
  from the same rows and rules as the website, so every surface agrees.

  - Status and days left: status.php, as the dashboard.
  - "Soon": the record's next date (next_payment), the same date reminders
    are planned from; recurring dates are not projected further ahead.
  - Monthly spending: the website's statistics formula (stats_calculations.php
    getPricePerMonth: days x30, weeks x4.35, months /frequency, years
    /(12 x frequency), one-time 0) over active subscriptions with a price, as
    the website's "monthly cost".
  - Currencies are never added up without a rate. Totals are kept per
    currency; a single total in the main currency is given only when every
    amount already is in it, or when the website's exchange job has refreshed
    the rates (last_exchange_update), converted with the website's own
    wallos_convert_price().
*/

require_once __DIR__ . '/dates.php';
require_once __DIR__ . '/status.php';
require_once __DIR__ . '/subscription_service.php';
require_once __DIR__ . '/../currency_rates.php';
require_once __DIR__ . '/../default_names.php';

const SHELFLIFE_REMINDER_DAYS_DEFAULT = 1; // the website's default when unset
const SHELFLIFE_REMINDER_DAYS_MAX = 7;     // the website offers 0..7 days before
const SHELFLIFE_SOON_HORIZON_DAYS = 30;

/**
 * Monthly equivalent of a price, by the website's statistics formula.
 */
function shelflife_monthly_equivalent($cycle, $frequency, $price)
{
    $frequency = max(1, (int) $frequency);
    $price = (float) $price;

    switch ((int) $cycle) {
        case SHELFLIFE_CYCLE_DAYS:
            return $price * (30 / $frequency);
        case SHELFLIFE_CYCLE_WEEKS:
            return $price * (4.35 / $frequency);
        case SHELFLIFE_CYCLE_MONTHS:
            return $price / $frequency;
        case SHELFLIFE_CYCLE_YEARS:
            return $price / (12 * $frequency);
        default:
            return 0.0;
    }
}

/**
 * The account as Telegram shows it, with its reminder setting.
 *
 * @return array|null null for an unknown user
 */
function shelflife_overview_account(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('SELECT id, username, firstname, main_currency, language, telegram_username FROM user WHERE id = :id');
    $stmt->bindValue(':id', (int) $userId, SQLITE3_INTEGER);
    $user = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($user === false) {
        return null;
    }

    return [
        'username' => html_entity_decode((string) $user['username'], ENT_QUOTES, 'UTF-8'),
        'first_name' => html_entity_decode((string) ($user['firstname'] ?? ''), ENT_QUOTES, 'UTF-8'),
        'main_currency_id' => (int) $user['main_currency'],
        'language' => (string) ($user['language'] ?? 'en'),
        'telegram_username' => $user['telegram_username'],
        'reminder_days' => shelflife_reminder_days($db, $userId),
    ];
}

/**
 * Days before the due date a reminder goes out when a record says "default":
 * the account's notification setting on the website.
 */
function shelflife_reminder_days(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('SELECT days FROM notification_settings WHERE user_id = :userId LIMIT 1');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return ($row === false || $row['days'] === null) ? SHELFLIFE_REMINDER_DAYS_DEFAULT : max(0, (int) $row['days']);
}

/**
 * Sets that account setting, as the website's notification settings do.
 *
 * @throws ShelfLifeValidationError
 */
function shelflife_set_reminder_days(SQLite3 $db, $userId, $days)
{
    $days = shelflife_to_int_in_range('reminder_days', $days, 0, SHELFLIFE_REMINDER_DAYS_MAX);

    $exists = $db->prepare('SELECT 1 FROM notification_settings WHERE user_id = :userId LIMIT 1');
    $exists->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $sql = $exists->execute()->fetchArray() === false
        ? 'INSERT INTO notification_settings (days, user_id) VALUES (:days, :userId)'
        : 'UPDATE notification_settings SET days = :days WHERE user_id = :userId';

    $stmt = $db->prepare($sql);
    $stmt->bindValue(':days', $days, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to save the reminder setting: ' . $db->lastErrorMsg());
    }

    return $days;
}

/**
 * The account's currencies: id => [id, code, symbol, name].
 */
function shelflife_overview_currencies(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('SELECT id, code, symbol, name FROM currencies WHERE user_id = :userId ORDER BY id');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $result = $stmt->execute();
    $currencies = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $currencies[(int) $row['id']] = [
            'id' => (int) $row['id'],
            'code' => (string) $row['code'],
            'symbol' => html_entity_decode((string) $row['symbol'], ENT_QUOTES, 'UTF-8'),
            'name' => html_entity_decode((string) $row['name'], ENT_QUOTES, 'UTF-8'),
        ];
    }

    return $currencies;
}

/**
 * The account's categories in the website's order: id => [id, name, none].
 * "none" marks the account's "no category" (in its language or Wallos's
 * English default), which is shown as having no category.
 */
function shelflife_overview_categories(SQLite3 $db, $userId, $language)
{
    $noCategory = [default_no_category_name((string) $language), 'No category'];
    $stmt = $db->prepare('SELECT id, name FROM categories WHERE user_id = :userId ORDER BY "order", id');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $result = $stmt->execute();
    $categories = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $name = trim(html_entity_decode((string) $row['name'], ENT_QUOTES, 'UTF-8'));
        $categories[(int) $row['id']] = ['id' => (int) $row['id'], 'name' => $name, 'none' => $name === '' || in_array($name, $noCategory, true)];
    }

    return $categories;
}

/**
 * Every record of the account, as Telegram shows it: active ones first, by date.
 *
 * @param string $today Y-m-d
 * @return array[]
 */
function shelflife_overview_records(SQLite3 $db, $userId, $today, array $currencies, array $categories)
{
    $stmt = $db->prepare('SELECT id, kind, name, price, currency_id, cycle, frequency, next_payment, inactive, notify,
                                 notify_days_before, snoozed_until, auto_renew, category_id
                          FROM subscriptions WHERE user_id = :userId
                          ORDER BY inactive ASC, next_payment ASC, name COLLATE NOCASE ASC, id ASC');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $result = $stmt->execute();

    $records = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $validDate = shelflife_is_valid_date($row['next_payment']);
        $inactive = (int) $row['inactive'] === 1;
        $kind = in_array($row['kind'], SHELFLIFE_KINDS, true) ? $row['kind'] : SHELFLIFE_KIND_SUBSCRIPTION;
        $cycle = (int) $row['cycle'];
        $price = (float) $row['price'];
        $category = $categories[(int) $row['category_id']] ?? null;
        $currency = $currencies[(int) $row['currency_id']] ?? null;
        $recurring = shelflife_is_recurring_cycle($cycle);
        $payable = !$inactive && $kind === SHELFLIFE_KIND_SUBSCRIPTION && $price > 0;

        $records[] = [
            'id' => (int) $row['id'],
            'kind' => $kind,
            'name' => html_entity_decode((string) $row['name'], ENT_QUOTES, 'UTF-8'),
            'next_payment' => $validDate ? $row['next_payment'] : null,
            'days_left' => $validDate ? shelflife_days_left($row['next_payment'], $today) : null,
            'status' => $inactive ? 'inactive' : ($validDate ? shelflife_record_status($row['next_payment'], $today) : 'ok'),
            'price' => $price,
            'currency' => $currency,
            'cycle' => $cycle,
            'frequency' => max(1, (int) $row['frequency']),
            'recurring' => $recurring,
            'category' => $category === null ? null : ['id' => $category['id'], 'name' => $category['none'] ? null : $category['name']],
            'inactive' => $inactive,
            'notify' => (int) $row['notify'] === 1,
            'notify_days_before' => $row['notify_days_before'] === null ? null : (int) $row['notify_days_before'],
            'snoozed_until' => shelflife_is_valid_date($row['snoozed_until']) ? $row['snoozed_until'] : null,
            'auto_renew' => (int) $row['auto_renew'] === 1,
            'monthly' => ($payable && $recurring) ? shelflife_monthly_equivalent($cycle, $row['frequency'], $price) : null,
        ];
    }

    return $records;
}

/**
 * Counts and the nearest date, for the home screen.
 */
function shelflife_overview_summary(array $records)
{
    $summary = ['active' => 0, 'inactive' => 0, 'overdue' => 0, 'today' => 0, 'week' => 0,
                'by_kind' => array_fill_keys(SHELFLIFE_KINDS, 0), 'nearest' => null];

    foreach ($records as $record) {
        if ($record['inactive']) {
            $summary['inactive']++;
            continue;
        }
        $summary['active']++;
        $summary['by_kind'][$record['kind']]++;
        $days = $record['days_left'];
        if ($days === null) {
            continue;
        }
        if ($days < 0) {
            $summary['overdue']++;
        } elseif ($days === 0) {
            $summary['today']++;
        }
        if ($days >= 0 && $days <= 7) {
            $summary['week']++;
        }
        if ($days >= 0 && ($summary['nearest'] === null || $days < $summary['nearest']['days_left'])) {
            $summary['nearest'] = $record;
        }
    }

    return $summary;
}

/**
 * Active records due within the horizon (and overdue ones), grouped:
 * overdue, today, tomorrow, week (2-7 days), month (8-30 days).
 *
 * @return array ['groups' => [['key' => ..., 'records' => [...]], ...], 'later' => int]
 */
function shelflife_overview_upcoming(array $records, $horizon = SHELFLIFE_SOON_HORIZON_DAYS)
{
    $groups = ['overdue' => [], 'today' => [], 'tomorrow' => [], 'week' => [], 'month' => []];
    $later = 0;

    foreach ($records as $record) {
        if ($record['inactive'] || $record['days_left'] === null) {
            continue;
        }
        $days = $record['days_left'];
        if ($days > $horizon) {
            $later++;
            continue;
        }
        $key = $days < 0 ? 'overdue' : ($days === 0 ? 'today' : ($days === 1 ? 'tomorrow' : ($days <= 7 ? 'week' : 'month')));
        $groups[$key][] = $record;
    }

    $result = [];
    foreach ($groups as $key => $items) {
        if ($items !== []) {
            $result[] = ['key' => $key, 'records' => $items];
        }
    }

    return ['groups' => $result, 'later' => $later];
}

/**
 * The date the website's exchange job last refreshed the account's rates, or
 * null when it never has (then the rates are not real and nothing is converted).
 */
function shelflife_rates_date(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('SELECT date FROM last_exchange_update WHERE user_id = :userId LIMIT 1');
    if ($stmt === false) {
        return null;
    }
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return ($row === false || !shelflife_is_valid_date($row['date'])) ? null : $row['date'];
}

/**
 * Spending: monthly equivalents per currency, a converted total when it is
 * honest to give one, the most expensive subscriptions, categories, and the
 * payments due in the next 30 days.
 */
function shelflife_overview_expenses(SQLite3 $db, $userId, array $records, $mainCurrencyId, array $currencies)
{
    $recurring = array_values(array_filter($records, fn($r) => $r['monthly'] !== null));
    $usedCurrencies = array_values(array_unique(array_map(fn($r) => $r['currency']['id'] ?? 0, $recurring)));
    $ratesDate = shelflife_rates_date($db, $userId);
    $allInMain = $usedCurrencies === [] || $usedCurrencies === [(int) $mainCurrencyId];
    $convertible = $allInMain || $ratesDate !== null;
    $inMain = fn(array $r) => $allInMain ? $r['monthly'] : wallos_convert_price($r['monthly'], $r['currency']['id'] ?? 0, $db, $userId);

    $perCurrency = [];
    foreach ($recurring as $r) {
        $id = $r['currency']['id'] ?? 0;
        $perCurrency[$id] ??= ['currency' => $r['currency'], 'monthly' => 0.0, 'count' => 0];
        $perCurrency[$id]['monthly'] += $r['monthly'];
        $perCurrency[$id]['count']++;
    }
    uksort($perCurrency, fn($a, $b) => [(int) ($a !== (int) $mainCurrencyId), $a] <=> [(int) ($b !== (int) $mainCurrencyId), $b]);

    $total = null;
    if ($convertible && $recurring !== []) {
        $total = ['currency' => $currencies[(int) $mainCurrencyId] ?? null, 'monthly' => 0.0, 'rates_date' => $allInMain ? null : $ratesDate];
        foreach ($recurring as $r) {
            $total['monthly'] += $inMain($r);
        }
    }

    // Most expensive first; across currencies only when they can be compared.
    $top = $recurring;
    usort($top, function ($a, $b) use ($convertible, $inMain, $mainCurrencyId) {
        if ($convertible) {
            return $inMain($b) <=> $inMain($a);
        }
        $order = fn($r) => (int) (($r['currency']['id'] ?? 0) !== (int) $mainCurrencyId);
        return [$order($a), $a['currency']['id'] ?? 0, -$a['monthly']] <=> [$order($b), $b['currency']['id'] ?? 0, -$b['monthly']];
    });
    $top = array_map(fn($r) => ['id' => $r['id'], 'name' => $r['name'], 'monthly' => $r['monthly'], 'currency' => $r['currency']], array_slice($top, 0, 5));

    // Categories, in the main currency when convertible, otherwise within the main currency only.
    $byCategory = [];
    foreach ($recurring as $r) {
        if (!$convertible && ($r['currency']['id'] ?? 0) !== (int) $mainCurrencyId) {
            continue;
        }
        $name = $r['category']['name'] ?? null;
        $key = $name ?? '';
        $byCategory[$key] ??= ['name' => $name, 'monthly' => 0.0, 'count' => 0];
        $byCategory[$key]['monthly'] += $convertible ? $inMain($r) : $r['monthly'];
        $byCategory[$key]['count']++;
    }
    usort($byCategory, fn($a, $b) => $b['monthly'] <=> $a['monthly']);

    // Payments due in the next 30 days: the amounts themselves, per currency.
    $due = [];
    foreach ($records as $r) {
        if ($r['inactive'] || $r['kind'] !== SHELFLIFE_KIND_SUBSCRIPTION || $r['price'] <= 0 || $r['days_left'] === null
            || $r['days_left'] < 0 || $r['days_left'] > SHELFLIFE_SOON_HORIZON_DAYS) {
            continue;
        }
        $id = $r['currency']['id'] ?? 0;
        $due[$id] ??= ['currency' => $r['currency'], 'amount' => 0.0, 'count' => 0];
        $due[$id]['amount'] += $r['price'];
        $due[$id]['count']++;
    }

    return [
        'per_currency' => array_values($perCurrency),
        'total' => $total,
        'convertible' => $convertible,
        'top' => $top,
        'by_category' => array_values($byCategory),
        'category_scope' => $convertible ? 'all' : 'main',
        'due_30_days' => array_values($due),
    ];
}

/**
 * Everything Telegram shows of the account, in one structure.
 *
 * @param string $today Y-m-d
 * @return array|null null for an unknown user
 */
function shelflife_overview(SQLite3 $db, $userId, $today)
{
    $account = shelflife_overview_account($db, $userId);
    if ($account === null) {
        return null;
    }

    $currencies = shelflife_overview_currencies($db, $userId);
    $categories = shelflife_overview_categories($db, $userId, $account['language']);
    $records = shelflife_overview_records($db, $userId, $today, $currencies, $categories);

    return [
        'today' => $today,
        'account' => $account,
        'currencies' => array_values($currencies),
        'categories' => array_values(array_map(fn($c) => ['id' => $c['id'], 'name' => $c['none'] ? null : $c['name']], $categories)),
        'records' => $records,
        'summary' => shelflife_overview_summary($records),
        'upcoming' => shelflife_overview_upcoming($records),
        'expenses' => shelflife_overview_expenses($db, $userId, $records, $account['main_currency_id'], $currencies),
    ];
}
