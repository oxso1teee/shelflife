<?php
/*
  ShelfLife bot actions (includes/shelflife/bot_actions.php): /add and the
  notification buttons, on behalf of a linked Telegram account.

  Records created from Telegram get the defaults the web form would preselect;
  buttons act only on the user's own record and only on the due date they were
  sent for; a repeated Telegram update changes nothing a second time.
*/

require_once WALLOS_ROOT . '/includes/shelflife/bot_actions.php';

function shelflife_bot_test_user(SQLite3 $db, $id, $name)
{
    wallos_test_create_user($db, $id, $name);
    $db->exec("INSERT INTO categories (name, \"order\", user_id) VALUES ('General', 1, $id)");
    $db->exec("INSERT INTO household (name, user_id) VALUES ('$name', $id)");
    $db->exec("INSERT INTO payment_methods (name, icon, \"order\", user_id) VALUES ('Card', '', 1, $id)");
    $db->exec("UPDATE user SET telegram_id = " . (1000 + $id) . " WHERE id = $id");

    return shelflife_link_find_user($db, 1000 + $id);
}

wallos_test('/add creates a record with the web form\'s defaults', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');

    $result = shelflife_bot_add_record($db, $alice, ['name' => 'Spotify & Co', 'next_payment' => '2026-11-15', 'price' => '500', 'currency' => 'usd'], '2026-10-13');

    assert_same('created', $result['status'], 'created');
    $record = $result['record'];
    assert_same('Spotify & Co', $record['name'], 'the bot gets the plain name back');
    assert_same(SHELFLIFE_KIND_SUBSCRIPTION, $record['kind'], 'a subscription by default');
    assert_same(SHELFLIFE_CYCLE_MONTHS, $record['cycle'], 'monthly by default');
    assert_same('USD', $record['currency'], 'the currency code is matched case-insensitively');

    $row = shelflife_subscription_find($db, 1, $record['id']);
    assert_same(1, $row['notify'], 'reminders are on');
    assert_same(-1, $row['notify_days_before'], 'using the default reminder settings');
    assert_true($row['category_id'] !== null && $row['payer_user_id'] !== null && $row['payment_method_id'] !== null,
        'category, payer and payment method are preselected');
    assert_same(15, $row['anchor_day'], 'anchored on its day');

    $db->close();
});

wallos_test('/add for a shelf-life date needs no price and does not repeat', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');

    $result = shelflife_bot_add_record($db, $alice, ['kind' => 'expiry', 'name' => 'Vitamins', 'next_payment' => '2026-12-01'], '2026-10-13');

    assert_same('created', $result['status'], 'created');
    assert_same(SHELFLIFE_CYCLE_ONE_TIME, $result['record']['cycle'], 'one-time');
    assert_same(0.0, $result['record']['price'], 'free');

    $db->close();
});

wallos_test('/add reports what is wrong instead of guessing', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');

    $missingPrice = shelflife_bot_add_record($db, $alice, ['name' => 'Netflix', 'next_payment' => '2026-11-15'], '2026-10-13');
    assert_same(['invalid', 'price'], [$missingPrice['status'], $missingPrice['field']], 'a subscription without a price');

    $badCurrency = shelflife_bot_add_record($db, $alice, ['name' => 'Netflix', 'next_payment' => '2026-11-15', 'price' => '5', 'currency' => 'XYZ'], '2026-10-13');
    assert_same(['invalid', 'currency'], [$badCurrency['status'], $badCurrency['field']], 'a currency the user does not have');

    $badDate = shelflife_bot_add_record($db, $alice, ['name' => 'Netflix', 'next_payment' => '2026-02-30', 'price' => '5'], '2026-10-13');
    assert_same(['invalid', 'next_payment'], [$badDate['status'], $badDate['field']], 'an impossible date');

    assert_same(0, $db->querySingle('SELECT COUNT(*) FROM subscriptions WHERE user_id = 1'), 'nothing was created');

    $db->close();
});

wallos_test('a repeated Telegram update is answered once and changes nothing', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $add = fn() => shelflife_bot_add_record($db, $alice, ['name' => 'Spotify', 'next_payment' => '2026-11-15', 'price' => '5'], '2026-10-13');

    $first = shelflife_bot_once($db, 777, 1001, $add);
    $second = shelflife_bot_once($db, 777, 1001, $add);

    assert_same(1, $db->querySingle('SELECT COUNT(*) FROM subscriptions WHERE user_id = 1'), 'one record');
    assert_same($first['record']['id'], $second['record']['id'], 'the same answer');
    assert_same(true, $second['repeated'] ?? false, 'marked as a repeat');

    $db->close();
});

/**
 * Runs $body with error_log() going to a temporary file and returns what was logged.
 */
function shelflife_bot_test_capture_log(callable $body)
{
    $file = tempnam(sys_get_temp_dir(), 'shelflife-log-');
    $previous = ini_set('error_log', $file);
    try {
        $body();
    } finally {
        ini_set('error_log', $previous === false ? '' : $previous);
    }
    $logged = (string) file_get_contents($file);
    unlink($file);

    return $logged;
}

wallos_test('a repeated button press from the same Telegram account is answered again and applied once', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $id = shelflife_bot_add_record($db, $alice, ['name' => 'Spotify', 'next_payment' => '2026-10-31', 'price' => '5'], '2026-10-13')['record']['id'];
    $runs = 0;
    $renew = function () use ($db, $alice, $id, &$runs) {
        $runs++;
        return shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'renew', 'expected_due' => '2026-10-31'], '2026-10-30');
    };

    shelflife_bot_once($db, 501, 1001, $renew);
    $again = shelflife_bot_once($db, 501, 1001, $renew);

    assert_same(1, $runs, 'the renewal ran once');
    assert_same(['done', '2026-11-30', true], [$again['status'], $again['record']['next_payment'], $again['repeated'] ?? false],
        'the same account gets its first answer again');
    assert_same('2026-11-30', shelflife_subscription_find($db, 1, $id)['next_payment'], 'renewed by one month, not two');

    $db->close();
});

wallos_test('another Telegram account never gets the stored answer to an update id', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $bob = shelflife_bot_test_user($db, 2, 'bob');
    $aliceAdds = fn() => shelflife_bot_add_record($db, $alice, ['name' => 'Private name', 'next_payment' => '2026-11-15', 'price' => '5'], '2026-10-13');
    $bobRuns = 0;
    $bobAdds = function () use ($db, $bob, &$bobRuns) {
        $bobRuns++;
        return shelflife_bot_add_record($db, $bob, ['name' => 'Bob', 'next_payment' => '2026-11-15', 'price' => '5'], '2026-10-13');
    };

    $first = shelflife_bot_once($db, 777, 1001, $aliceAdds);
    $stored = $db->querySingle('SELECT telegram_id, response FROM telegram_processed_updates WHERE update_id = 777', true);

    $replay = null;
    $logged = shelflife_bot_test_capture_log(function () use ($db, $bobAdds, &$replay) {
        $replay = shelflife_bot_once($db, 777, 1002, $bobAdds);
    });

    assert_same(['status' => 'invalid'], $replay, 'refused, and nothing of alice\'s answer is in it');
    assert_same(0, $bobRuns, 'bob\'s /add was not run under alice\'s update id');
    assert_same([1, 0], [
        (int) $db->querySingle('SELECT COUNT(*) FROM subscriptions WHERE user_id = 1'),
        (int) $db->querySingle('SELECT COUNT(*) FROM subscriptions WHERE user_id = 2'),
    ], 'nothing was created a second time, and nothing for bob');
    assert_same($stored, $db->querySingle('SELECT telegram_id, response FROM telegram_processed_updates WHERE update_id = 777', true),
        'the stored answer still belongs to alice, unchanged');
    assert_contains('update 777 was already processed for another account', $logged, 'the refusal is logged');
    assert_not_contains('1001', $logged, 'the log names no Telegram account');
    assert_not_contains('Private name', $logged, 'nor the record');

    $aliceAgain = shelflife_bot_once($db, 777, 1001, $aliceAdds);
    assert_same([$first['record']['id'], true], [$aliceAgain['record']['id'], $aliceAgain['repeated'] ?? false],
        'alice herself still gets her answer');

    $db->close();
});

wallos_test('a button press replayed from another account changes and reveals nothing', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $bob = shelflife_bot_test_user($db, 2, 'bob');
    $id = shelflife_bot_add_record($db, $alice, ['name' => 'Private name', 'next_payment' => '2026-10-31', 'price' => '5'], '2026-10-13')['record']['id'];
    $act = fn(array $user, $action, $due) => fn() => shelflife_bot_act($db, $user, ['subscription_id' => $id, 'action' => $action, 'expected_due' => $due], '2026-10-30');

    shelflife_bot_once($db, 502, 1001, $act($alice, 'renew', '2026-10-31'));

    shelflife_bot_test_capture_log(function () use ($db, $act, $bob) {
        foreach (['renew', 'cancel', 'snooze'] as $action) {
            $replay = shelflife_bot_once($db, 502, 1002, $act($bob, $action, '2026-11-30'));
            assert_same(['status' => 'invalid'], $replay, 'bob\'s ' . $action . ' under alice\'s update id is refused without content');
        }
    });

    $row = shelflife_subscription_find($db, 1, $id);
    assert_same(['2026-11-30', 0, null], [$row['next_payment'], $row['inactive'], $row['snoozed_until']],
        'alice\'s record was renewed once by her own press and nothing else');

    $db->close();
});

wallos_test('buttons renew, cancel and snooze the user\'s own record once', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $id = shelflife_bot_add_record($db, $alice, ['name' => 'Spotify', 'next_payment' => '2026-10-31', 'price' => '5'], '2026-10-13')['record']['id'];

    $renew = shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'renew', 'expected_due' => '2026-10-31'], '2026-10-30');
    assert_same(['done', '2026-11-30'], [$renew['status'], $renew['record']['next_payment']], 'renewed into November');

    $again = shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'renew', 'expected_due' => '2026-10-31'], '2026-10-30');
    assert_same(['stale', '2026-11-30'], [$again['status'], $again['record']['next_payment']], 'the old button no longer applies');

    $snooze = shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'snooze', 'expected_due' => '2026-11-30'], '2026-11-29');
    assert_same(['done', '2026-11-30'], [$snooze['status'], $snooze['record']['snoozed_until']], 'reminder moved to tomorrow');

    $cancel = shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'cancel', 'expected_due' => '2026-11-30'], '2026-11-29');
    assert_same(['done', true], [$cancel['status'], $cancel['record']['inactive']], 'cancelled');
    assert_same('2026-11-29', shelflife_subscription_find($db, 1, $id)['cancellation_date'], 'with the date it was cancelled');
    assert_same('inactive', shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'renew', 'expected_due' => '2026-11-30'], '2026-11-29')['status'], 'an inactive record cannot be renewed');

    $db->close();
});

wallos_test('"extended by a month" moves a shelf-life date by one calendar month', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $id = shelflife_bot_add_record($db, $alice, ['kind' => 'expiry', 'name' => 'Milk', 'next_payment' => '2027-01-31'], '2026-10-13')['record']['id'];

    $renew = shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'renew', 'expected_due' => '2027-01-31'], '2027-01-30');
    assert_same('2027-02-28', $renew['record']['next_payment'], 'clamped to February');

    $db->close();
});

wallos_test('a button cannot touch another user\'s record', function () {
    $db = wallos_test_open_database();
    $alice = shelflife_bot_test_user($db, 1, 'alice');
    $bob = shelflife_bot_test_user($db, 2, 'bob');
    $id = shelflife_bot_add_record($db, $alice, ['name' => 'Spotify', 'next_payment' => '2026-10-31', 'price' => '5'], '2026-10-13')['record']['id'];

    foreach (['renew', 'cancel', 'snooze'] as $action) {
        $result = shelflife_bot_act($db, $bob, ['subscription_id' => $id, 'action' => $action, 'expected_due' => '2026-10-31'], '2026-10-30');
        assert_same('not_found', $result['status'], 'bob cannot ' . $action . ' alice\'s record');
    }
    $row = shelflife_subscription_find($db, 1, $id);
    assert_same(['2026-10-31', 0, null], [$row['next_payment'], $row['inactive'], $row['snoozed_until']], 'alice\'s record is untouched');

    assert_same('invalid', shelflife_bot_act($db, $alice, ['subscription_id' => $id, 'action' => 'archive', 'expected_due' => '2026-10-31'], '2026-10-30')['status'], 'unknown action');

    $db->close();
});
