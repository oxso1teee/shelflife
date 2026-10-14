<?php
/*
  ShelfLife record service (includes/shelflife/subscription_service.php).

  The web form, the public API, the bot's internal API and the cron jobs all
  write records through this service, so it is where ownership, validation,
  record kinds and due-date moves are checked. Every case runs against the real
  schema, migrations included.
*/

require_once WALLOS_ROOT . '/includes/shelflife/subscription_service.php';

function shelflife_test_input(array $overrides = [])
{
    return $overrides + [
        'name' => 'Spotify',
        'price' => '9.99',
        'currency_id' => wallos_test_currency_id(1, 0),
        'cycle' => SHELFLIFE_CYCLE_MONTHS,
        'frequency' => 1,
        'next_payment' => '2025-01-31',
    ];
}

function shelflife_test_rejects(callable $callback, $field)
{
    try {
        $callback();
    } catch (ShelfLifeValidationError $e) {
        return $e->field === $field;
    }

    return false;
}

function shelflife_test_add(SQLite3 $db, $userId, array $overrides = [])
{
    $input = shelflife_test_input($overrides + ['currency_id' => wallos_test_currency_id($userId, 0)]);
    return shelflife_subscription_insert($db, $userId, shelflife_subscription_prepare($db, $userId, $input));
}

wallos_test('the migration adds the ShelfLife columns and can run twice', function () {
    $db = wallos_test_open_database();

    $columns = [];
    $result = $db->query("SELECT name FROM pragma_table_info('subscriptions')");
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $columns[] = $row['name'];
    }
    foreach (['kind', 'anchor_day', 'snoozed_until'] as $column) {
        assert_true(in_array($column, $columns, true), 'subscriptions has ' . $column);
    }

    wallos_test_create_user($db, 1, 'alice');
    $db->exec("INSERT INTO subscriptions (name, price, currency_id, next_payment, cycle, frequency, user_id, anchor_day)
               VALUES ('Old monthly', 5, " . wallos_test_currency_id(1, 0) . ", '2025-03-31', 3, 1, 1, NULL)");

    ob_start();
    require WALLOS_ROOT . '/migrations/000060.php';
    require WALLOS_ROOT . '/migrations/000060.php';
    ob_end_clean();

    assert_same(31, $db->querySingle("SELECT anchor_day FROM subscriptions WHERE name = 'Old monthly'"), 'existing monthly records anchor on their due day');
    assert_same('subscription', $db->querySingle("SELECT kind FROM subscriptions WHERE name = 'Old monthly'"), 'existing records are subscriptions');

    $db->close();
});

wallos_test('required fields and value ranges are enforced', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');

    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['name' => '  '])), 'name'), 'empty name');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['price' => ''])), 'price'), 'a subscription without a price');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['price' => '-1'])), 'price'), 'negative price');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['price' => '1e999'])), 'price'), 'infinite price');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['price' => 'NAN'])), 'price'), 'not a number');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['next_payment' => '2025-02-30'])), 'next_payment'), 'impossible date');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['cycle' => 7])), 'cycle'), 'unknown cycle');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['frequency' => 0])), 'frequency'), 'frequency 0');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['kind' => 'loan'])), 'kind'), 'unknown kind');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['notify_days_before' => 500])), 'notify_days_before'), 'reminder too far ahead');

    $data = shelflife_subscription_prepare($db, 1, shelflife_test_input(['price' => '9,99']));
    assert_same(9.99, $data['price'], 'a decimal comma is accepted');

    $db->close();
});

wallos_test('another user\'s currency, category or record cannot be referenced', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    wallos_test_create_user($db, 2, 'bob');
    $db->exec("INSERT INTO categories (id, name, user_id) VALUES (7001, 'Bob only', 2)");
    $bobsRecord = shelflife_test_add($db, 2, ['name' => 'Bob Netflix']);

    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['currency_id' => wallos_test_currency_id(2, 0)])), 'currency_id'), 'foreign currency');
    assert_true(shelflife_test_rejects(fn() => shelflife_subscription_prepare($db, 1, shelflife_test_input(['category_id' => 7001])), 'category_id'), 'foreign category');

    $data = shelflife_subscription_prepare($db, 1, shelflife_test_input(['inactive' => true, 'replacement_subscription_id' => $bobsRecord]));
    assert_same(null, $data['replacement_subscription_id'], 'a foreign replacement is dropped');

    assert_same(null, shelflife_subscription_find($db, 1, $bobsRecord), 'alice cannot read bob\'s record');
    $aliceData = shelflife_subscription_prepare($db, 1, shelflife_test_input(['name' => 'Hijack']));
    assert_same(false, shelflife_subscription_update($db, 1, $bobsRecord, $aliceData), 'alice cannot update bob\'s record');
    assert_same('Bob Netflix', shelflife_subscription_find($db, 2, $bobsRecord)['name'], 'bob\'s record is untouched');

    $db->close();
});

wallos_test('shelf-life and maintenance records need no price', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');

    $expiry = shelflife_subscription_prepare($db, 1, shelflife_test_input([
        'kind' => SHELFLIFE_KIND_EXPIRY, 'name' => 'Vitamins', 'price' => '', 'cycle' => SHELFLIFE_CYCLE_ONE_TIME,
        'frequency' => 12, 'auto_renew' => true, 'cancellation_date' => '2025-05-01', 'next_payment' => '2025-06-15',
    ]));
    assert_same(0.0, $expiry['price'], 'no price means zero');
    assert_same(1, $expiry['frequency'], 'a one-time record has frequency 1');
    assert_same(0, $expiry['auto_renew'], 'a one-time record never auto-renews');
    assert_same(null, $expiry['cancellation_date'], 'a one-time record has nothing to cancel');
    assert_same(null, $expiry['anchor_day'], 'and no anchor');

    $maintenance = shelflife_subscription_prepare($db, 1, shelflife_test_input([
        'kind' => SHELFLIFE_KIND_MAINTENANCE, 'name' => 'Water filter', 'price' => null, 'frequency' => 3, 'next_payment' => '2025-08-31',
    ]));
    assert_same(SHELFLIFE_KIND_MAINTENANCE, $maintenance['kind'], 'kind is kept');
    assert_same(31, $maintenance['anchor_day'], 'a quarterly record anchors on its day');

    $db->close();
});

wallos_test('editing keeps the anchor and does not re-encode stored text', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $id = shelflife_test_add($db, 1, ['name' => 'Tom & Jerry', 'next_payment' => '2025-01-31']);
    // Written directly: validate_markdown() strips backslashes on input, so only
    // a stored value can carry one, and a later edit must not strip it.
    $db->exec("UPDATE subscriptions SET notes = 'path\\to' WHERE id = " . (int) $id);

    $renew = shelflife_subscription_renew($db, 1, $id, '2025-01-20');
    assert_same('2025-02-28', $renew['next_payment'], 'clamped to February');

    $existing = shelflife_subscription_find($db, 1, $id);
    assert_same('Tom &amp; Jerry', $existing['name'], 'stored once encoded');

    // An API edit that only changes the price.
    shelflife_subscription_update($db, 1, $id, shelflife_subscription_prepare($db, 1, ['price' => '11'], $existing));
    $edited = shelflife_subscription_find($db, 1, $id);
    assert_same('Tom &amp; Jerry', $edited['name'], 'not encoded a second time');
    assert_same('path\\to', $edited['notes'], 'stored notes keep their backslash');
    assert_same(31, $edited['anchor_day'], 'the anchor survives a save that keeps the due date');

    // The web form re-posts every field, including the clamped date.
    shelflife_subscription_update($db, 1, $id, shelflife_subscription_prepare($db, 1, shelflife_test_input(['name' => 'Tom & Jerry', 'next_payment' => '2025-02-28']), $edited));
    assert_same(31, shelflife_subscription_find($db, 1, $id)['anchor_day'], 'a full re-save of the same date keeps the anchor');

    // A new date set by the user becomes the new anchor.
    shelflife_subscription_update($db, 1, $id, shelflife_subscription_prepare($db, 1, ['next_payment' => '2025-03-15'], shelflife_subscription_find($db, 1, $id)));
    assert_same(15, shelflife_subscription_find($db, 1, $id)['anchor_day'], 'a changed date re-anchors');

    $db->close();
});

wallos_test('renewing moves to the next period once, and a repeat is stale', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    wallos_test_create_user($db, 2, 'bob');
    $id = shelflife_test_add($db, 1, ['next_payment' => '2025-01-31']);

    $first = shelflife_subscription_renew($db, 1, $id, '2025-01-30', '2025-01-31');
    assert_same(['status' => 'renewed', 'next_payment' => '2025-02-28'], $first, 'renewed into February');

    $again = shelflife_subscription_renew($db, 1, $id, '2025-01-30', '2025-01-31');
    assert_same('stale', $again['status'], 'the same confirmation a second time changes nothing');
    assert_same('2025-02-28', shelflife_subscription_find($db, 1, $id)['next_payment'], 'still February');

    $next = shelflife_subscription_renew($db, 1, $id, '2025-02-27', '2025-02-28');
    assert_same('2025-03-31', $next['next_payment'], 'back to the 31st');

    $overdue = shelflife_test_add($db, 1, ['next_payment' => '2025-01-31']);
    assert_same('2025-04-30', shelflife_subscription_renew($db, 1, $overdue, '2025-04-10')['next_payment'], 'an overdue record jumps to the next date not in the past');

    assert_same('not_found', shelflife_subscription_renew($db, 2, $id, '2025-03-01')['status'], 'bob cannot renew alice\'s record');

    $oneTime = shelflife_test_add($db, 1, ['kind' => SHELFLIFE_KIND_EXPIRY, 'cycle' => SHELFLIFE_CYCLE_ONE_TIME, 'price' => '']);
    assert_same('not_recurring', shelflife_subscription_renew($db, 1, $oneTime, '2025-01-01')['status'], 'a one-time record cannot be renewed');

    $db->close();
});

wallos_test('the daily job moves overdue auto-renewals and nothing else', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $currency = wallos_test_currency_id(1, 0);

    $auto = shelflife_test_add($db, 1, ['next_payment' => '2025-01-31', 'auto_renew' => true]);
    $manual = shelflife_test_add($db, 1, ['next_payment' => '2025-01-31', 'auto_renew' => false]);
    $inactive = shelflife_test_add($db, 1, ['next_payment' => '2025-01-31', 'auto_renew' => true, 'inactive' => true]);
    $daily = shelflife_test_add($db, 1, ['next_payment' => '2025-02-27', 'cycle' => SHELFLIFE_CYCLE_DAYS, 'auto_renew' => true]);
    $dueToday = shelflife_test_add($db, 1, ['next_payment' => '2025-03-01', 'auto_renew' => true]);
    // A one-time row with auto_renew set, as an old form or a direct write could leave it.
    $db->exec("INSERT INTO subscriptions (name, price, currency_id, next_payment, cycle, frequency, auto_renew, inactive, user_id)
               VALUES ('Old one-time', 0, $currency, '2025-01-10', 5, 1, 1, 0, 1)");
    $oneTime = $db->lastInsertRowID();

    $moved = shelflife_advance_overdue_auto_renewals($db, '2025-03-01');

    assert_same(2, $moved, 'two records were overdue and auto-renewing');
    assert_same('2025-03-31', shelflife_subscription_find($db, 1, $auto)['next_payment'], 'monthly: next 31st');
    assert_same('2025-03-01', shelflife_subscription_find($db, 1, $daily)['next_payment'], 'daily: today, not tomorrow');
    assert_same('2025-01-31', shelflife_subscription_find($db, 1, $manual)['next_payment'], 'manual renewal waits for the user');
    assert_same('2025-01-31', shelflife_subscription_find($db, 1, $inactive)['next_payment'], 'inactive is left alone');
    assert_same('2025-03-01', shelflife_subscription_find($db, 1, $dueToday)['next_payment'], 'due today is not overdue');
    assert_same('2025-01-10', shelflife_subscription_find($db, 1, $oneTime)['next_payment'], 'one-time records are skipped');

    assert_same(0, shelflife_advance_overdue_auto_renewals($db, '2025-03-01'), 'a second run the same day changes nothing');

    $db->close();
});
