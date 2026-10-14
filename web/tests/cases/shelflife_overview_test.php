<?php
/*
  What Telegram shows of an account (includes/shelflife/overview.php): records,
  "soon", spending and settings, by the website's rules — and the record
  operations Telegram adds (reactivate, delete).
*/

require_once WALLOS_ROOT . '/includes/shelflife/overview.php';
require_once WALLOS_ROOT . '/includes/shelflife/bot_actions.php';

function shelflife_overview_test_setup()
{
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    wallos_test_create_user($db, 2, 'bob');
    foreach ([1, 2] as $userId) {
        $db->exec("INSERT INTO categories (name, \"order\", user_id) VALUES ('No category', 1, $userId)");
        $db->exec("INSERT INTO categories (name, \"order\", user_id) VALUES ('Музыка &amp; кино', 2, $userId)");
    }

    return $db;
}

function shelflife_overview_test_record(SQLite3 $db, $userId, array $fields)
{
    $input = $fields + [
        'kind' => 'subscription',
        'price' => '10',
        'currency_id' => wallos_test_currency_id($userId, 0),
        'cycle' => SHELFLIFE_CYCLE_MONTHS,
        'frequency' => 1,
        'next_payment' => '2026-11-15',
    ];

    return shelflife_subscription_insert($db, $userId, shelflife_subscription_prepare($db, $userId, $input));
}

function shelflife_overview_test_category($db, $userId, $name)
{
    return (int) $db->querySingle("SELECT id FROM categories WHERE user_id = $userId AND name = '" . SQLite3::escapeString($name) . "'");
}

wallos_test('the monthly equivalent follows the website\'s statistics formula', function () {
    assert_same(30.0, shelflife_monthly_equivalent(SHELFLIFE_CYCLE_DAYS, 1, 1), 'daily: x30');
    assert_same(8.7, round(shelflife_monthly_equivalent(SHELFLIFE_CYCLE_WEEKS, 1, 2), 2), 'weekly: x4.35');
    assert_same(4.0, shelflife_monthly_equivalent(SHELFLIFE_CYCLE_MONTHS, 3, 12), 'every 3 months: /3');
    assert_same(5.0, shelflife_monthly_equivalent(SHELFLIFE_CYCLE_YEARS, 2, 120), 'every 2 years: /24');
    assert_same(0.0, shelflife_monthly_equivalent(SHELFLIFE_CYCLE_ONE_TIME, 1, 99), 'one-time: 0');
});

wallos_test('records are shown with status, category and monthly cost, active ones first', function () {
    $db = shelflife_overview_test_setup();
    $music = shelflife_overview_test_category($db, 1, 'Музыка &amp; кино');
    shelflife_overview_test_record($db, 1, ['name' => 'Spotify & Co', 'category_id' => $music, 'next_payment' => '2026-11-03']);
    shelflife_overview_test_record($db, 1, ['name' => 'Milk', 'kind' => 'expiry', 'price' => '', 'cycle' => 5, 'next_payment' => '2026-11-01',
        'category_id' => shelflife_overview_test_category($db, 1, 'No category')]);
    shelflife_overview_test_record($db, 1, ['name' => 'Old', 'inactive' => true, 'next_payment' => '2026-10-01']);
    shelflife_overview_test_record($db, 2, ['name' => 'Bob\'s']);

    $overview = shelflife_overview($db, 1, '2026-11-01');
    $records = $overview['records'];

    assert_same(['Milk', 'Spotify & Co', 'Old'], array_column($records, 'name'), 'only alice\'s records; active first, by date; names decoded');
    assert_same(['soon', 'soon', 'inactive'], array_column($records, 'status'), 'status as on the dashboard: under 7 days is "soon"');
    assert_same([0, 2, -31], array_column($records, 'days_left'), 'days left');
    assert_same('Музыка & кино', $records[1]['category']['name'], 'a real category, decoded');
    assert_same(null, $records[0]['category']['name'], '"No category" is shown as none');
    assert_same([null, 10.0, null], array_column($records, 'monthly'), 'monthly cost only for an active subscription with a price');
    assert_same('EUR', $records[1]['currency']['code'], 'the currency');
    $categoryNames = array_column($overview['categories'], 'name');
    assert_true(in_array('Музыка & кино', $categoryNames, true), 'categories for the forms, decoded');
    assert_true(!in_array('No category', $categoryNames, true) && in_array(null, $categoryNames, true), '"No category" offered as none');

    $db->close();
});

wallos_test('the summary and "soon" group active records by their next date', function () {
    $db = shelflife_overview_test_setup();
    foreach (['Late' => '2026-10-30', 'Today' => '2026-11-01', 'Tomorrow' => '2026-11-02', 'Week' => '2026-11-08',
              'Month' => '2026-11-20', 'Later' => '2027-01-01'] as $name => $date) {
        shelflife_overview_test_record($db, 1, ['name' => $name, 'next_payment' => $date]);
    }
    shelflife_overview_test_record($db, 1, ['name' => 'Off', 'inactive' => true, 'next_payment' => '2026-11-01']);

    $overview = shelflife_overview($db, 1, '2026-11-01');
    $groups = [];
    foreach ($overview['upcoming']['groups'] as $group) {
        $groups[$group['key']] = array_column($group['records'], 'name');
    }

    assert_same(['overdue' => ['Late'], 'today' => ['Today'], 'tomorrow' => ['Tomorrow'], 'week' => ['Week'], 'month' => ['Month']], $groups, 'groups');
    assert_same(1, $overview['upcoming']['later'], 'one further away');
    $summary = $overview['summary'];
    assert_same([6, 1, 1, 1, 3], [$summary['active'], $summary['inactive'], $summary['overdue'], $summary['today'], $summary['week']], 'counts');
    assert_same('Today', $summary['nearest']['name'], 'the nearest date that has not passed');

    $db->close();
});

wallos_test('spending is not added up across currencies without real exchange rates', function () {
    $db = shelflife_overview_test_setup();
    $music = shelflife_overview_test_category($db, 1, 'Музыка &amp; кино');
    shelflife_overview_test_record($db, 1, ['name' => 'Netflix', 'price' => '12', 'category_id' => $music]);
    shelflife_overview_test_record($db, 1, ['name' => 'Cloud', 'price' => '120', 'cycle' => SHELFLIFE_CYCLE_YEARS]);
    shelflife_overview_test_record($db, 1, ['name' => 'Tool', 'price' => '11', 'currency_id' => wallos_test_currency_id(1, 1)]);
    shelflife_overview_test_record($db, 1, ['name' => 'Course', 'price' => '300', 'cycle' => 5]);
    shelflife_overview_test_record($db, 1, ['name' => 'Gone', 'price' => '50', 'inactive' => true]);
    shelflife_overview_test_record($db, 1, ['name' => 'Filter', 'kind' => 'maintenance', 'price' => '40']);

    $expenses = shelflife_overview($db, 1, '2026-11-01')['expenses'];

    assert_same([['EUR', 22.0, 2], ['USD', 11.0, 1]], array_map(fn($c) => [$c['currency']['code'], round($c['monthly'], 2), $c['count']], $expenses['per_currency']),
        'per currency: Netflix 12 + Cloud 120/12 in EUR; Tool in USD; one-time, inactive and maintenance left out');
    assert_same(null, $expenses['total'], 'no single total: the rates were never refreshed');
    assert_same(false, $expenses['convertible'], 'and that is said');
    assert_same(['Netflix', 'Cloud', 'Tool'], array_column($expenses['top'], 'name'), 'main currency first, then by cost');
    assert_same('main', $expenses['category_scope'], 'categories within the main currency only');
    assert_same([['Музыка & кино', 12.0], [null, 10.0]], array_map(fn($c) => [$c['name'], round($c['monthly'], 2)], $expenses['by_category']), 'by category');
    assert_same([['EUR', 432.0, 3], ['USD', 11.0, 1]], array_map(fn($c) => [$c['currency']['code'], $c['amount'], $c['count']], $expenses['due_30_days']),
        'due within 30 days: the amounts themselves, one-time purchase included');

    $db->close();
});

wallos_test('with refreshed rates, spending is converted as the website converts', function () {
    $db = shelflife_overview_test_setup();
    shelflife_overview_test_record($db, 1, ['name' => 'Netflix', 'price' => '12']);
    shelflife_overview_test_record($db, 1, ['name' => 'Tool', 'price' => '11', 'currency_id' => wallos_test_currency_id(1, 1)]);
    $db->exec("INSERT INTO last_exchange_update (date, user_id) VALUES ('2026-10-31', 1)");

    $expenses = shelflife_overview($db, 1, '2026-11-01')['expenses'];

    assert_same(true, $expenses['convertible'], 'convertible');
    assert_same(['EUR', 22.0, '2026-10-31'], [$expenses['total']['currency']['code'], round($expenses['total']['monthly'], 2), $expenses['total']['rates_date']],
        'USD 11 at 1.1 is EUR 10: total EUR 22, with the rates\' date');
    assert_same(['Netflix', 'Tool'], array_column($expenses['top'], 'name'), 'compared in the main currency');

    $db->close();
});

wallos_test('everything in the main currency gives a total without rates', function () {
    $db = shelflife_overview_test_setup();
    shelflife_overview_test_record($db, 1, ['name' => 'A', 'price' => '5']);
    shelflife_overview_test_record($db, 1, ['name' => 'B', 'price' => '7.5']);

    $total = shelflife_overview($db, 1, '2026-11-01')['expenses']['total'];

    assert_same([12.5, null], [$total['monthly'], $total['rates_date']], 'a plain sum');

    $db->close();
});

wallos_test('the default reminder is the website\'s notification setting, 0 to 7 days', function () {
    $db = shelflife_overview_test_setup();

    assert_same(1, shelflife_reminder_days($db, 1), 'the website\'s default without a setting');
    assert_same(3, shelflife_set_reminder_days($db, 1, 3), 'saved');
    assert_same(3, shelflife_reminder_days($db, 1), 'read back');
    shelflife_set_reminder_days($db, 1, 0);
    assert_same(0, shelflife_reminder_days($db, 1), 'on the day itself; the row is updated, not duplicated');
    assert_same(1, $db->querySingle('SELECT COUNT(*) FROM notification_settings WHERE user_id = 1'), 'one row');
    assert_same(1, shelflife_reminder_days($db, 2), 'bob is untouched');

    $refused = null;
    try {
        shelflife_set_reminder_days($db, 1, 8);
    } catch (ShelfLifeValidationError $e) {
        $refused = $e->field;
    }
    assert_same('reminder_days', $refused, 'more than the website offers is refused');

    $db->close();
});

wallos_test('a record is deleted as on the website, with its queued reminders', function () {
    $db = shelflife_overview_test_setup();
    $id = shelflife_overview_test_record($db, 1, ['name' => 'Spotify']);
    $replaced = shelflife_overview_test_record($db, 1, ['name' => 'Old', 'inactive' => true, 'replacement_subscription_id' => $id]);
    $bobs = shelflife_overview_test_record($db, 2, ['name' => 'Bob\'s']);
    $db->exec("INSERT INTO telegram_outbox (user_id, subscription_id, due_date, remind_on, status, created_at) VALUES (1, $id, '2026-11-15', '2026-11-14', 'pending', 1)");

    assert_same('stale', shelflife_subscription_delete($db, 1, $id, '2026-12-01')['status'], 'an old card does not delete a changed record');
    assert_same('not_found', shelflife_subscription_delete($db, 1, $bobs)['status'], 'alice cannot delete bob\'s record');
    assert_same('deleted', shelflife_subscription_delete($db, 1, $id, '2026-11-15')['status'], 'deleted');

    assert_same(null, shelflife_subscription_find($db, 1, $id), 'gone');
    assert_same(null, shelflife_subscription_find($db, 1, $replaced)['replacement_subscription_id'], 'no longer named as a replacement');
    assert_same(0, $db->querySingle("SELECT COUNT(*) FROM telegram_outbox WHERE subscription_id = $id"), 'its reminders are gone');
    assert_same('Bob&#039;s', shelflife_subscription_find($db, 2, $bobs)['name'], 'bob\'s record stays');
    assert_same('not_found', shelflife_subscription_delete($db, 1, $id)['status'], 'a second delete finds nothing');

    $db->close();
});

wallos_test('a cancelled record can be made active again', function () {
    $db = shelflife_overview_test_setup();
    $id = shelflife_overview_test_record($db, 1, ['name' => 'Spotify']);
    shelflife_subscription_cancel($db, 1, $id, '2026-11-01', '2026-11-15');
    $planned = shelflife_overview_test_record($db, 1, ['name' => 'Planned', 'inactive' => true, 'cancellation_date' => '2027-01-01']);

    assert_same('stale', shelflife_subscription_reactivate($db, 1, $id, '2026-11-02', '2026-12-15')['status'], 'an old card');
    assert_same('reactivated', shelflife_subscription_reactivate($db, 1, $id, '2026-11-02', '2026-11-15')['status'], 'reactivated');
    $row = shelflife_subscription_find($db, 1, $id);
    assert_same([0, null], [$row['inactive'], $row['cancellation_date']], 'active, the cancellation date that came is cleared');
    assert_same('active', shelflife_subscription_reactivate($db, 1, $id, '2026-11-02', '2026-11-15')['status'], 'a second press changes nothing');

    shelflife_subscription_reactivate($db, 1, $planned, '2026-11-02', '2026-11-15');
    assert_same('2027-01-01', shelflife_subscription_find($db, 1, $planned)['cancellation_date'], 'a planned cancellation in the future stays');

    $db->close();
});

wallos_test('the bot can reactivate and delete through its action, for its own records only', function () {
    $db = shelflife_overview_test_setup();
    $db->exec('UPDATE user SET telegram_id = 1001 WHERE id = 1');
    $db->exec('UPDATE user SET telegram_id = 1002 WHERE id = 2');
    $alice = shelflife_link_find_user($db, 1001);
    $bob = shelflife_link_find_user($db, 1002);
    $id = shelflife_overview_test_record($db, 1, ['name' => 'Spotify', 'inactive' => true]);

    $act = fn($user, $action) => shelflife_bot_act($db, $user, ['subscription_id' => $id, 'action' => $action, 'expected_due' => '2026-11-15'], '2026-11-01');

    assert_same('not_found', $act($bob, 'reactivate')['status'], 'bob cannot reactivate it');
    assert_same('not_found', $act($bob, 'delete')['status'], 'nor delete it');
    $reactivated = $act($alice, 'reactivate');
    assert_same(['done', false], [$reactivated['status'], $reactivated['record']['inactive']], 'alice reactivates it');
    assert_same(['done', 'delete', null], [$act($alice, 'delete')['status'], 'delete', $act($alice, 'delete')['record'] ?? null], 'and deletes it');
    assert_same(null, shelflife_subscription_find($db, 1, $id), 'gone');

    $db->close();
});
