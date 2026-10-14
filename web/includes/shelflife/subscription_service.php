<?php
/*
  ShelfLife: the one place that validates and writes records.

  The web form (endpoints/subscription/add.php), the public API
  (api/subscriptions/set_subscriptions.php), the bot's internal API and the
  cron jobs all go through these functions, so ownership checks, date rules and
  record kinds cannot drift apart between them. Logo files stay with the callers
  that receive uploads; only the resulting file names are passed in here.
*/

require_once __DIR__ . '/../inputvalidation.php';
require_once __DIR__ . '/dates.php';

const SHELFLIFE_KIND_SUBSCRIPTION = 'subscription';
const SHELFLIFE_KIND_EXPIRY = 'expiry';
const SHELFLIFE_KIND_MAINTENANCE = 'maintenance';
const SHELFLIFE_KINDS = [SHELFLIFE_KIND_SUBSCRIPTION, SHELFLIFE_KIND_EXPIRY, SHELFLIFE_KIND_MAINTENANCE];

/**
 * Raised for input a caller should report back to the user.
 */
class ShelfLifeValidationError extends RuntimeException
{
    /** @var string */
    public $field;

    public function __construct($field, $message)
    {
        parent::__construct($message);
        $this->field = $field;
    }
}

/**
 * @return array|null The user's record, or null if it does not exist or belongs to someone else.
 */
function shelflife_subscription_find(SQLite3 $db, $userId, $id)
{
    $stmt = $db->prepare('SELECT * FROM subscriptions WHERE id = :id AND user_id = :userId');
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return $row === false ? null : $row;
}

/**
 * Whether row $id of $table belongs to the user. Payment methods may also be
 * the shared defaults Wallos stores without an owner.
 */
function shelflife_owns_row(SQLite3 $db, $table, $id, $userId)
{
    $queries = [
        'currencies' => 'SELECT id FROM currencies WHERE id = :id AND user_id = :userId',
        'categories' => 'SELECT id FROM categories WHERE id = :id AND user_id = :userId',
        'household' => 'SELECT id FROM household WHERE id = :id AND user_id = :userId',
        'payment_methods' => 'SELECT id FROM payment_methods WHERE id = :id AND (user_id = :userId OR user_id = 0 OR user_id IS NULL)',
        'subscriptions' => 'SELECT id FROM subscriptions WHERE id = :id AND user_id = :userId',
    ];

    $stmt = $db->prepare($queries[$table]);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $result = $stmt->execute();

    return $result !== false && $result->fetchArray() !== false;
}

function shelflife_is_blank($value)
{
    return $value === null || (is_string($value) && trim($value) === '');
}

function shelflife_to_bool($value)
{
    if (is_bool($value)) {
        return $value;
    }

    return in_array(is_string($value) ? strtolower(trim($value)) : $value, [1, '1', 'true', 'on', 'yes'], true);
}

/**
 * @return int|null
 */
function shelflife_to_int_in_range($field, $value, $min, $max)
{
    if (is_int($value)) {
        $int = $value;
    } elseif (is_string($value) && preg_match('/^\s*-?\d+\s*$/', $value)) {
        $int = (int) $value;
    } else {
        throw new ShelfLifeValidationError($field, sprintf('"%s" must be a whole number.', $field));
    }

    if ($int < $min || $int > $max) {
        throw new ShelfLifeValidationError($field, sprintf('"%s" must be between %d and %d.', $field, $min, $max));
    }

    return $int;
}

/**
 * @return float
 */
function shelflife_to_price($value)
{
    if (is_string($value)) {
        $value = str_replace(',', '.', trim($value));
    }

    if (!is_numeric($value)) {
        throw new ShelfLifeValidationError('price', '"price" must be a number.');
    }

    $price = (float) $value;
    if (!is_finite($price) || $price < 0) {
        throw new ShelfLifeValidationError('price', '"price" must be zero or more.');
    }

    return $price;
}

/**
 * Validates input for a new record or changes to an existing one and returns
 * the full set of column values to store.
 *
 * Keys missing from $input keep the existing record's value ($existing), or
 * take the default for a new record. A caller that posts a whole form passes
 * every key, so an unticked checkbox has to be passed as false.
 *
 * @param array      $input    raw values keyed by column name
 * @param array|null $existing the current row when editing
 * @return array column => value
 * @throws ShelfLifeValidationError
 */
function shelflife_subscription_prepare(SQLite3 $db, $userId, array $input, $existing = null)
{
    $defaults = [
        'kind' => SHELFLIFE_KIND_SUBSCRIPTION,
        'name' => null,
        'price' => null,
        'currency_id' => null,
        'frequency' => 1,
        'cycle' => null,
        'next_payment' => null,
        'start_date' => null,
        'auto_renew' => 1,
        'payment_method_id' => null,
        'payer_user_id' => null,
        'category_id' => null,
        'notes' => '',
        'url' => '',
        'notify' => 0,
        'notify_days_before' => null,
        'inactive' => 0,
        'cancellation_date' => null,
        'replacement_subscription_id' => null,
    ];

    $value = function ($key) use ($input, $existing, $defaults) {
        if (array_key_exists($key, $input)) {
            return $input[$key];
        }

        return $existing !== null && array_key_exists($key, $existing) ? $existing[$key] : $defaults[$key];
    };
    // Text is sanitised when it comes in. A stored value is already sanitised,
    // and running validate() over it again would encode "&amp;" twice.
    $isNew = fn($key) => array_key_exists($key, $input) || $existing === null;

    $data = [];

    $kind = shelflife_is_blank($value('kind')) ? SHELFLIFE_KIND_SUBSCRIPTION : trim((string) $value('kind'));
    if (!in_array($kind, SHELFLIFE_KINDS, true)) {
        throw new ShelfLifeValidationError('kind', '"kind" must be one of: ' . implode(', ', SHELFLIFE_KINDS) . '.');
    }
    $data['kind'] = $kind;

    $name = $isNew('name') ? validate((string) $value('name')) : (string) $value('name');
    if (trim($name) === '') {
        throw new ShelfLifeValidationError('name', 'The name cannot be empty.');
    }
    $data['name'] = $name;

    $price = $value('price');
    if (shelflife_is_blank($price)) {
        if ($kind === SHELFLIFE_KIND_SUBSCRIPTION) {
            throw new ShelfLifeValidationError('price', 'A subscription needs a price.');
        }
        $price = 0;
    }
    $data['price'] = shelflife_to_price($price);

    $currencyId = $value('currency_id');
    if (shelflife_is_blank($currencyId)) {
        throw new ShelfLifeValidationError('currency_id', 'A currency is required.');
    }
    $currencyId = shelflife_to_int_in_range('currency_id', $currencyId, 1, PHP_INT_MAX);
    if (!shelflife_owns_row($db, 'currencies', $currencyId, $userId)) {
        throw new ShelfLifeValidationError('currency_id', 'The specified currency does not exist or does not belong to you.');
    }
    $data['currency_id'] = $currencyId;

    $cycle = $value('cycle');
    if (shelflife_is_blank($cycle)) {
        throw new ShelfLifeValidationError('cycle', 'A cycle is required.');
    }
    $cycle = shelflife_to_int_in_range('cycle', $cycle, SHELFLIFE_CYCLE_DAYS, SHELFLIFE_CYCLE_ONE_TIME);
    $data['cycle'] = $cycle;

    if ($cycle === SHELFLIFE_CYCLE_ONE_TIME) {
        $data['frequency'] = 1;
    } else {
        $frequency = $value('frequency');
        $data['frequency'] = shelflife_to_int_in_range('frequency', shelflife_is_blank($frequency) ? 1 : $frequency, 1, 366);
    }

    $nextPayment = $value('next_payment');
    if (!shelflife_is_valid_date($nextPayment)) {
        throw new ShelfLifeValidationError('next_payment', 'The date must be a valid date in YYYY-MM-DD format.');
    }
    $data['next_payment'] = $nextPayment;

    $startDate = $value('start_date');
    if (shelflife_is_blank($startDate)) {
        $data['start_date'] = null;
    } elseif (shelflife_is_valid_date($startDate) || !$isNew('start_date')) {
        // A stored value is kept as it is, even in a format Wallos once wrote.
        $data['start_date'] = $startDate;
    } else {
        throw new ShelfLifeValidationError('start_date', 'The start date must be a valid date in YYYY-MM-DD format.');
    }

    // A one-time record has nothing to renew; the cron job would have no period to add.
    $data['auto_renew'] = $cycle === SHELFLIFE_CYCLE_ONE_TIME ? 0 : (shelflife_to_bool($value('auto_renew')) ? 1 : 0);

    foreach (['payment_method_id' => 'payment_methods', 'payer_user_id' => 'household', 'category_id' => 'categories'] as $field => $table) {
        $id = $value($field);
        if (shelflife_is_blank($id)) {
            $data[$field] = null;
            continue;
        }

        $id = shelflife_to_int_in_range($field, $id, 0, PHP_INT_MAX);
        if (!shelflife_owns_row($db, $table, $id, $userId)) {
            throw new ShelfLifeValidationError($field, sprintf('The specified %s does not exist or does not belong to you.', str_replace('_id', '', $field)));
        }
        $data[$field] = $id;
    }

    $data['notes'] = $isNew('notes') ? validate_markdown((string) $value('notes')) : (string) $value('notes');
    $data['url'] = $isNew('url') ? validate((string) $value('url')) : (string) $value('url');
    $data['notify'] = shelflife_to_bool($value('notify')) ? 1 : 0;

    $notifyDaysBefore = $value('notify_days_before');
    // -1 means "use the default from the notification settings", 0 means on the due date.
    $data['notify_days_before'] = shelflife_is_blank($notifyDaysBefore) ? null : shelflife_to_int_in_range('notify_days_before', $notifyDaysBefore, -1, 366);

    $data['inactive'] = shelflife_to_bool($value('inactive')) ? 1 : 0;

    $cancellationDate = $value('cancellation_date');
    if (shelflife_is_blank($cancellationDate) || $cycle === SHELFLIFE_CYCLE_ONE_TIME) {
        $data['cancellation_date'] = null;
    } elseif (shelflife_is_valid_date($cancellationDate) || !$isNew('cancellation_date')) {
        $data['cancellation_date'] = $cancellationDate;
    } else {
        throw new ShelfLifeValidationError('cancellation_date', 'The cancellation date must be a valid date in YYYY-MM-DD format.');
    }

    // Only an inactive record can point at the record that replaced it; an
    // unknown or foreign id is dropped, as Wallos always did.
    $replacementId = $value('replacement_subscription_id');
    $data['replacement_subscription_id'] = null;
    if ($data['inactive'] === 1 && !shelflife_is_blank($replacementId) && (string) $replacementId !== '0') {
        $replacementId = shelflife_to_int_in_range('replacement_subscription_id', $replacementId, 1, PHP_INT_MAX);
        if ($existing !== null && (int) $existing['id'] === $replacementId) {
            throw new ShelfLifeValidationError('replacement_subscription_id', 'A subscription cannot be replaced by itself.');
        }
        if (shelflife_owns_row($db, 'subscriptions', $replacementId, $userId)) {
            $data['replacement_subscription_id'] = $replacementId;
        }
    }

    // Keep the anchor while the due date is unchanged: re-saving a record
    // clamped to 28 February must not move it off the 31st for good.
    $dueDateUnchanged = $existing !== null && $existing['next_payment'] === $nextPayment;
    if (!in_array($cycle, [SHELFLIFE_CYCLE_MONTHS, SHELFLIFE_CYCLE_YEARS], true)) {
        $data['anchor_day'] = null;
    } elseif (array_key_exists('anchor_day', $input) && !shelflife_is_blank($input['anchor_day'])) {
        $data['anchor_day'] = shelflife_to_int_in_range('anchor_day', $input['anchor_day'], 1, 31);
    } elseif ($dueDateUnchanged && !shelflife_is_blank($existing['anchor_day'] ?? null)) {
        $data['anchor_day'] = (int) $existing['anchor_day'];
    } else {
        $data['anchor_day'] = shelflife_anchor_day($cycle, $nextPayment);
    }

    // A snooze belongs to one due date.
    $data['snoozed_until'] = $dueDateUnchanged ? ($existing['snoozed_until'] ?? null) : null;

    return $data;
}

/**
 * @return array SQLite3 type for each column the service writes.
 */
function shelflife_subscription_column_types()
{
    return [
        'kind' => SQLITE3_TEXT,
        'name' => SQLITE3_TEXT,
        'price' => SQLITE3_FLOAT,
        'currency_id' => SQLITE3_INTEGER,
        'frequency' => SQLITE3_INTEGER,
        'cycle' => SQLITE3_INTEGER,
        'next_payment' => SQLITE3_TEXT,
        'start_date' => SQLITE3_TEXT,
        'auto_renew' => SQLITE3_INTEGER,
        'payment_method_id' => SQLITE3_INTEGER,
        'payer_user_id' => SQLITE3_INTEGER,
        'category_id' => SQLITE3_INTEGER,
        'notes' => SQLITE3_TEXT,
        'url' => SQLITE3_TEXT,
        'notify' => SQLITE3_INTEGER,
        'notify_days_before' => SQLITE3_INTEGER,
        'inactive' => SQLITE3_INTEGER,
        'cancellation_date' => SQLITE3_TEXT,
        'replacement_subscription_id' => SQLITE3_INTEGER,
        'anchor_day' => SQLITE3_INTEGER,
        'snoozed_until' => SQLITE3_TEXT,
        'logo' => SQLITE3_TEXT,
        'logo_text_color' => SQLITE3_TEXT,
        'logo_variant' => SQLITE3_TEXT,
    ];
}

function shelflife_bind_columns(SQLite3Stmt $stmt, array $values)
{
    $types = shelflife_subscription_column_types();
    foreach ($values as $column => $value) {
        $stmt->bindValue(':' . $column, $value, $value === null ? SQLITE3_NULL : $types[$column]);
    }
}

/**
 * @param array $data output of shelflife_subscription_prepare()
 * @param array $logo optional logo, logo_text_color, logo_variant
 * @return int id of the new record
 */
function shelflife_subscription_insert(SQLite3 $db, $userId, array $data, array $logo = [])
{
    $values = $data + [
        'logo' => $logo['logo'] ?? '',
        'logo_text_color' => $logo['logo_text_color'] ?? null,
        'logo_variant' => $logo['logo_variant'] ?? null,
    ];

    $columns = array_keys($values);
    $sql = 'INSERT INTO subscriptions (' . implode(', ', $columns) . ', user_id) VALUES (:'
        . implode(', :', $columns) . ', :user_id)';

    $stmt = $db->prepare($sql);
    shelflife_bind_columns($stmt, $values);
    $stmt->bindValue(':user_id', (int) $userId, SQLITE3_INTEGER);

    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to add the record: ' . $db->lastErrorMsg());
    }

    return $db->lastInsertRowID();
}

/**
 * @param array|null $logo logo, logo_text_color, logo_variant to store; null keeps the current logo
 * @return bool whether the user's record was found and updated
 */
function shelflife_subscription_update(SQLite3 $db, $userId, $id, array $data, $logo = null)
{
    $values = $data;
    if ($logo !== null) {
        $values += [
            'logo' => $logo['logo'] ?? '',
            'logo_text_color' => $logo['logo_text_color'] ?? null,
            'logo_variant' => $logo['logo_variant'] ?? null,
        ];
    }

    $assignments = array_map(fn($column) => $column . ' = :' . $column, array_keys($values));
    $sql = 'UPDATE subscriptions SET ' . implode(', ', $assignments) . ' WHERE id = :id AND user_id = :user_id';

    $stmt = $db->prepare($sql);
    shelflife_bind_columns($stmt, $values);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':user_id', (int) $userId, SQLITE3_INTEGER);

    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to update the record: ' . $db->lastErrorMsg());
    }

    return $db->changes() > 0;
}

/**
 * Confirms the current period of a recurring record (paid, replaced, serviced)
 * and moves its due date to the next one that is not in the past.
 *
 * The update only applies while the record is still due on $expectedDue, so a
 * second confirmation of the same date — a double click, a retried request —
 * changes nothing and reports 'stale'.
 *
 * A one-time record is only moved when $allowOneTime is set (the bot's
 * "extended by a month" button); the dashboard renews recurring records only.
 *
 * @param string      $today        Y-m-d
 * @param string|null $expectedDue  due date the caller saw; null takes the current one
 * @param bool        $allowOneTime move a one-time record by one month
 * @return array ['status' => 'renewed'|'not_found'|'not_recurring'|'stale', 'next_payment' => ?string]
 */
function shelflife_subscription_renew(SQLite3 $db, $userId, $id, $today, $expectedDue = null, $allowOneTime = false)
{
    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found', 'next_payment' => null];
    }

    $cycle = (int) $row['cycle'];
    if (!shelflife_is_valid_date($row['next_payment'])) {
        return ['status' => 'not_recurring', 'next_payment' => $row['next_payment']];
    }

    $currentDue = $row['next_payment'];
    if ($expectedDue !== null && $expectedDue !== $currentDue) {
        return ['status' => 'stale', 'next_payment' => $currentDue];
    }

    if ((int) $row['inactive'] === 1) {
        return ['status' => 'inactive', 'next_payment' => $currentDue];
    }

    if (shelflife_is_recurring_cycle($cycle)) {
        $anchorDay = shelflife_is_blank($row['anchor_day'] ?? null) ? shelflife_anchor_day($cycle, $currentDue) : (int) $row['anchor_day'];
        $nextDue = shelflife_advance_until($currentDue, $cycle, max(1, (int) $row['frequency']), $anchorDay, $today, true);
    } elseif ($allowOneTime) {
        // "Extended by a month" on a one-time record (a shelf-life date) moves it
        // by one calendar month, as the specification words the button.
        $anchorDay = null;
        $nextDue = shelflife_add_period($currentDue, SHELFLIFE_CYCLE_MONTHS, 1);
    } else {
        return ['status' => 'not_recurring', 'next_payment' => $currentDue];
    }

    $stmt = $db->prepare('UPDATE subscriptions SET next_payment = :next, anchor_day = :anchor, snoozed_until = NULL
                          WHERE id = :id AND user_id = :userId AND next_payment = :current');
    $stmt->bindValue(':next', $nextDue, SQLITE3_TEXT);
    $stmt->bindValue(':anchor', $anchorDay, $anchorDay === null ? SQLITE3_NULL : SQLITE3_INTEGER);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->bindValue(':current', $currentDue, SQLITE3_TEXT);

    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to renew the record: ' . $db->lastErrorMsg());
    }

    if ($db->changes() === 0) {
        return ['status' => 'stale', 'next_payment' => $currentDue];
    }

    return ['status' => 'renewed', 'next_payment' => $nextDue];
}

/**
 * Stops tracking a record: a subscription the user cancelled, a product used up
 * or thrown away, equipment no longer serviced. The record becomes inactive,
 * like Wallos's "disabled" subscriptions: it leaves the totals and the
 * reminders but stays visible and can be re-enabled on the website.
 *
 * Applies only while the record is still active and due on $expectedDue, so a
 * repeated press changes nothing.
 *
 * @return array ['status' => 'cancelled'|'not_found'|'stale'|'inactive']
 */
function shelflife_subscription_cancel(SQLite3 $db, $userId, $id, $today, $expectedDue)
{
    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found'];
    }
    if ((int) $row['inactive'] === 1) {
        return ['status' => 'inactive'];
    }
    if ($row['next_payment'] !== $expectedDue) {
        return ['status' => 'stale'];
    }

    // A recurring subscription records when it was cancelled; a one-time record
    // has nothing to cancel in Wallos's sense, so it is only made inactive.
    $stmt = $db->prepare('UPDATE subscriptions
                          SET inactive = 1, snoozed_until = NULL,
                              cancellation_date = CASE WHEN cycle = 5 THEN NULL ELSE :today END
                          WHERE id = :id AND user_id = :userId AND inactive = 0 AND next_payment = :due');
    $stmt->bindValue(':today', $today, SQLITE3_TEXT);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->bindValue(':due', $expectedDue, SQLITE3_TEXT);
    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to cancel the record: ' . $db->lastErrorMsg());
    }

    return ['status' => $db->changes() === 1 ? 'cancelled' : 'stale'];
}

/**
 * Postpones the reminder for the current due date to $days days from $today.
 * The due date itself does not move.
 *
 * @return array ['status' => 'snoozed'|'not_found'|'stale'|'inactive', 'snoozed_until' => ?string]
 */
function shelflife_subscription_snooze(SQLite3 $db, $userId, $id, $today, $expectedDue, $days = 1)
{
    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found', 'snoozed_until' => null];
    }
    if ((int) $row['inactive'] === 1) {
        return ['status' => 'inactive', 'snoozed_until' => null];
    }
    if ($row['next_payment'] !== $expectedDue) {
        return ['status' => 'stale', 'snoozed_until' => null];
    }

    $until = shelflife_add_period($today, SHELFLIFE_CYCLE_DAYS, max(1, (int) $days));

    $stmt = $db->prepare('UPDATE subscriptions SET snoozed_until = :until
                          WHERE id = :id AND user_id = :userId AND inactive = 0 AND next_payment = :due');
    $stmt->bindValue(':until', $until, SQLITE3_TEXT);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->bindValue(':due', $expectedDue, SQLITE3_TEXT);
    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to snooze the record: ' . $db->lastErrorMsg());
    }

    if ($db->changes() !== 1) {
        return ['status' => 'stale', 'snoozed_until' => null];
    }

    return ['status' => 'snoozed', 'snoozed_until' => $until];
}

/**
 * Makes a cancelled (inactive) record active again, as unticking "inactive" on
 * the website does. A cancellation date that has come is cleared with it; a
 * planned one in the future stays.
 *
 * @return array ['status' => 'reactivated'|'not_found'|'stale'|'active']
 */
function shelflife_subscription_reactivate(SQLite3 $db, $userId, $id, $today, $expectedDue)
{
    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found'];
    }
    if ((int) $row['inactive'] === 0) {
        return ['status' => 'active'];
    }
    if ($row['next_payment'] !== $expectedDue) {
        return ['status' => 'stale'];
    }

    $stmt = $db->prepare('UPDATE subscriptions
                          SET inactive = 0,
                              cancellation_date = CASE WHEN cancellation_date <= :today THEN NULL ELSE cancellation_date END
                          WHERE id = :id AND user_id = :userId AND inactive = 1 AND next_payment = :due');
    $stmt->bindValue(':today', $today, SQLITE3_TEXT);
    $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->bindValue(':due', $expectedDue, SQLITE3_TEXT);
    if ($stmt->execute() === false) {
        throw new RuntimeException('Failed to reactivate the record: ' . $db->lastErrorMsg());
    }

    return ['status' => $db->changes() === 1 ? 'reactivated' : 'stale'];
}

/**
 * Deletes the user's record the way the website does
 * (endpoints/subscription/delete.php): other records stop pointing at it as
 * their replacement, and its logo files go if nothing else uses them. Its
 * queued Telegram reminders go too.
 *
 * @param string|null $expectedDue when given, the record must still be due on it
 * @param string|null $logosDir    the logos directory (default: the app's)
 * @return array ['status' => 'deleted'|'not_found'|'stale']
 */
function shelflife_subscription_delete(SQLite3 $db, $userId, $id, $expectedDue = null, $logosDir = null)
{
    $row = shelflife_subscription_find($db, $userId, $id);
    if ($row === null) {
        return ['status' => 'not_found'];
    }
    if ($expectedDue !== null && $row['next_payment'] !== $expectedDue) {
        return ['status' => 'stale'];
    }

    $statements = [
        'DELETE FROM subscriptions WHERE id = :id AND user_id = :userId',
        'UPDATE subscriptions SET replacement_subscription_id = NULL WHERE replacement_subscription_id = :id AND user_id = :userId',
        'DELETE FROM telegram_outbox WHERE subscription_id = :id AND user_id = :userId',
    ];
    // A savepoint, not BEGIN: the bot and the Mini App call this inside the
    // transaction of shelflife_bot_once(), and SQLite does not nest BEGIN.
    $db->exec('SAVEPOINT shelflife_delete');
    try {
        foreach ($statements as $sql) {
            $stmt = $db->prepare($sql);
            $stmt->bindValue(':id', (int) $id, SQLITE3_INTEGER);
            $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
            if ($stmt->execute() === false) {
                throw new RuntimeException('Failed to delete the record: ' . $db->lastErrorMsg());
            }
        }
        $db->exec('RELEASE shelflife_delete');
    } catch (Throwable $e) {
        $db->exec('ROLLBACK TO shelflife_delete');
        $db->exec('RELEASE shelflife_delete');
        throw $e;
    }

    require_once __DIR__ . '/../logo_cleanup.php';
    $logosDir = $logosDir ?? __DIR__ . '/../../images/uploads/logos/';
    deleteLogoFileIfUnused($db, $row['logo'] ?? '', $logosDir);
    deleteLogoFileIfUnused($db, $row['logo_variant'] ?? '', $logosDir);

    return ['status' => 'deleted'];
}

/**
 * Moves every automatically renewing record whose due date has passed to its
 * next due date on or after $today. Run daily by
 * endpoints/cronjobs/updatenextpayment.php.
 *
 * @param string $today Y-m-d
 * @return int number of records moved
 */
function shelflife_advance_overdue_auto_renewals(SQLite3 $db, $today)
{
    $select = $db->prepare('SELECT id, next_payment, cycle, frequency, anchor_day FROM subscriptions
                            WHERE auto_renew = 1 AND inactive = 0 AND cycle IN (1, 2, 3, 4) AND next_payment < :today');
    $select->bindValue(':today', $today, SQLITE3_TEXT);
    $result = $select->execute();

    $due = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $due[] = $row;
    }

    $update = $db->prepare('UPDATE subscriptions SET next_payment = :next, anchor_day = :anchor, snoozed_until = NULL
                            WHERE id = :id AND next_payment = :current');

    $moved = 0;
    foreach ($due as $row) {
        if (!shelflife_is_valid_date($row['next_payment'])) {
            continue;
        }

        $cycle = (int) $row['cycle'];
        $anchorDay = shelflife_is_blank($row['anchor_day']) ? shelflife_anchor_day($cycle, $row['next_payment']) : (int) $row['anchor_day'];
        $nextDue = shelflife_advance_until($row['next_payment'], $cycle, max(1, (int) $row['frequency']), $anchorDay, $today);

        $update->bindValue(':next', $nextDue, SQLITE3_TEXT);
        $update->bindValue(':anchor', $anchorDay, $anchorDay === null ? SQLITE3_NULL : SQLITE3_INTEGER);
        $update->bindValue(':id', (int) $row['id'], SQLITE3_INTEGER);
        $update->bindValue(':current', $row['next_payment'], SQLITE3_TEXT);
        $update->execute();
        $moved += $db->changes();
        $update->reset();
    }

    return $moved;
}
