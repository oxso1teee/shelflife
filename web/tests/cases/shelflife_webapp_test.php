<?php
/*
  The Telegram Mini App on the server: init data signed by Telegram is the
  only proof of who is asking (includes/shelflife/webapp_auth.php), and the
  operations act on that account's records only (includes/shelflife/webapp_api.php).
*/

require_once WALLOS_ROOT . '/includes/shelflife/webapp_auth.php';
require_once WALLOS_ROOT . '/includes/shelflife/webapp_api.php';

const SHELFLIFE_WEBAPP_TEST_TOKEN = '123456:TEST-token-for-the-mini-app-tests';

/**
 * Init data as Telegram builds it, signed with $token.
 */
function shelflife_webapp_test_init_data(array $fields, $token = SHELFLIFE_WEBAPP_TEST_TOKEN)
{
    ksort($fields, SORT_STRING);
    $lines = [];
    foreach ($fields as $key => $value) {
        $lines[] = $key . '=' . $value;
    }
    $fields['hash'] = hash_hmac('sha256', implode("\n", $lines), hash_hmac('sha256', $token, 'WebAppData', true));

    return http_build_query($fields, '', '&', PHP_QUERY_RFC3986);
}

function shelflife_webapp_test_user_field($id)
{
    return json_encode(['id' => $id, 'first_name' => 'Анна', 'username' => 'anna_tg', 'language_code' => 'ru']);
}

function shelflife_webapp_test_setup()
{
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    wallos_test_create_user($db, 2, 'bob');
    $db->exec('UPDATE user SET telegram_id = 1001 WHERE id = 1');
    $db->exec('UPDATE user SET telegram_id = 1002 WHERE id = 2');

    return [$db, shelflife_link_find_user($db, 1001), shelflife_link_find_user($db, 1002)];
}

function shelflife_webapp_test_record(SQLite3 $db, $userId, array $fields = [])
{
    $input = $fields + ['name' => 'Spotify', 'price' => '10', 'currency_id' => wallos_test_currency_id($userId, 0),
                        'cycle' => SHELFLIFE_CYCLE_MONTHS, 'frequency' => 1, 'next_payment' => '2026-11-15'];

    return shelflife_subscription_insert($db, $userId, shelflife_subscription_prepare($db, $userId, $input));
}

wallos_test('signed init data identifies the Telegram user', function () {
    $now = 1_800_000_000;
    $initData = shelflife_webapp_test_init_data(['auth_date' => (string) ($now - 60), 'query_id' => 'AAH', 'user' => shelflife_webapp_test_user_field(1001),
                                                 'signature' => 'ed25519-signature-from-telegram']);

    $result = shelflife_webapp_verify($initData, SHELFLIFE_WEBAPP_TEST_TOKEN, $now);

    assert_same(true, $result['ok'], 'valid');
    assert_same([1001, 'anna_tg'], [$result['user']['id'], $result['user']['username']], 'the user from the signed data');
});

wallos_test('init data that is not exactly what Telegram signed is refused', function () {
    $now = 1_800_000_000;
    $fields = ['auth_date' => (string) ($now - 60), 'user' => shelflife_webapp_test_user_field(1001)];
    $valid = shelflife_webapp_test_init_data($fields);
    $reason = fn($initData, $token = SHELFLIFE_WEBAPP_TEST_TOKEN, $at = null) => shelflife_webapp_verify($initData, $token, $at ?? $now)['reason'] ?? 'ok';

    assert_same('bad_hash', $reason(str_replace(rawurlencode('"id":1001'), rawurlencode('"id":1002'), $valid)), 'another user id in the same data');
    assert_same('bad_hash', $reason($valid, '654321:another-bot-token'), 'signed for another bot');
    assert_same('bad_hash', $reason($valid . '&extra=1'), 'a field added');
    assert_same('missing_hash', $reason(preg_replace('/&?hash=[0-9a-f]+/', '', $valid)), 'no signature');
    assert_same('malformed', $reason($valid . '&user=' . rawurlencode(shelflife_webapp_test_user_field(1002))), 'a field given twice');
    assert_same('expired', $reason($valid, SHELFLIFE_WEBAPP_TEST_TOKEN, $now + SHELFLIFE_WEBAPP_MAX_AGE + 61), 'too old');
    assert_same('bad_auth_date', $reason(shelflife_webapp_test_init_data(['auth_date' => (string) ($now + 600)] + $fields)), 'from the future');
    assert_same('bad_user', $reason(shelflife_webapp_test_init_data(['auth_date' => (string) $now, 'user' => '{"id":"1001"}'])), 'a user id that is not a number');
    assert_same('bad_user', $reason(shelflife_webapp_test_init_data(['auth_date' => (string) $now])), 'no user');
    assert_same('missing', $reason(''), 'nothing at all');
    assert_same('no_bot_token', $reason($valid, ''), 'no bot token configured');
    assert_same('ok', $reason($valid), 'the original still passes');
});

wallos_test('the Mini App shows the signed-in account and nobody else\'s records', function () {
    [$db, $alice] = shelflife_webapp_test_setup();
    shelflife_webapp_test_record($db, 1, ['name' => 'Alice']);
    shelflife_webapp_test_record($db, 2, ['name' => 'Bob']);

    $answer = shelflife_webapp_handle($db, $alice, 1001, ['op' => 'state'], '2026-11-01');

    assert_same('ok', $answer['status'], 'ok');
    assert_same(['Alice'], array_column($answer['state']['records'], 'name'), 'only alice\'s');
    assert_same('alice', $answer['state']['account']['username'], 'her account');

    $db->close();
});

wallos_test('a record is created with the website\'s validation, once per request', function () {
    [$db, $alice] = shelflife_webapp_test_setup();
    $save = fn($record, $requestId) => shelflife_webapp_handle($db, $alice, 1001, ['op' => 'save', 'request_id' => $requestId, 'record' => $record], '2026-11-01');
    $record = ['kind' => 'subscription', 'name' => 'Netflix <HD>', 'price' => '9.99', 'currency_id' => wallos_test_currency_id(1, 1),
               'cycle' => SHELFLIFE_CYCLE_MONTHS, 'frequency' => 1, 'next_payment' => '2026-12-01'];

    assert_same(['invalid', 'price'], array_values(array_intersect_key($save(['price' => ''] + $record, 'req-missing-price'), ['status' => 1, 'field' => 1])),
        'a subscription without a price is refused');
    assert_same(['invalid', 'next_payment'], array_values(array_intersect_key($save(['next_payment' => '2026-02-30'] + $record, 'req-bad-date'), ['status' => 1, 'field' => 1])),
        'an impossible date is refused');

    $first = $save($record, 'req-create-netflix');
    $again = $save($record, 'req-create-netflix');
    assert_same('saved', $first['status'], 'saved');
    assert_same($first['id'], $again['id'], 'the repeated request answers the same record');
    assert_same(1, $db->querySingle("SELECT COUNT(*) FROM subscriptions WHERE user_id = 1 AND name LIKE 'Netflix%'"), 'created once');
    $created = shelflife_subscription_find($db, 1, $first['id']);
    assert_same(['Netflix &lt;HD&gt;', 9.99, 1, -1], [$created['name'], $created['price'], $created['notify'], $created['notify_days_before']],
        'stored as the website stores it, reminders on by default');
    assert_same('Netflix <HD>', array_values(array_filter($first['state']['records'], fn($r) => $r['id'] === $first['id']))[0]['name'], 'the fresh state shows it');

    $db->close();
});

wallos_test('a record is edited field by field, and only by its owner', function () {
    [$db, $alice, $bob] = shelflife_webapp_test_setup();
    $id = shelflife_webapp_test_record($db, 1, ['name' => 'Spotify', 'notes' => 'keep me']);
    $edit = fn($user, $telegramId, $fields, $requestId) => shelflife_webapp_handle($db, $user, $telegramId, ['op' => 'save', 'request_id' => $requestId, 'record' => ['id' => $id] + $fields], '2026-11-01');

    assert_same('not_found', $edit($bob, 1002, ['name' => 'Hacked'], 'req-bob-edit')['status'], 'bob cannot edit it');
    assert_same('saved', $edit($alice, 1001, ['price' => '12,50', 'next_payment' => '2026-11-20'], 'req-alice-edit')['status'], 'alice can');

    $row = shelflife_subscription_find($db, 1, $id);
    assert_same(['Spotify', 12.5, '2026-11-20', 'keep me'], [$row['name'], $row['price'], $row['next_payment'], $row['notes']],
        'the fields sent change, the others stay');

    $db->close();
});

wallos_test('Mini App actions renew, cancel, reactivate and delete, by the due date shown', function () {
    [$db, $alice, $bob] = shelflife_webapp_test_setup();
    $id = shelflife_webapp_test_record($db, 1);
    $act = fn($user, $telegramId, $action, $due, $requestId) => shelflife_webapp_handle($db, $user, $telegramId,
        ['op' => 'act', 'request_id' => $requestId, 'id' => $id, 'action' => $action, 'expected_due' => $due], '2026-11-14');

    assert_same('not_found', $act($bob, 1002, 'cancel', '2026-11-15', 'req-bob-cancel')['status'], 'bob cannot touch it');
    assert_same('done', $act($alice, 1001, 'renew', '2026-11-15', 'req-renew')['status'], 'renewed');
    assert_same('stale', $act($alice, 1001, 'renew', '2026-11-15', 'req-renew-again')['status'], 'the old date no longer applies');
    assert_same('done', $act($alice, 1001, 'cancel', '2026-12-15', 'req-cancel')['status'], 'cancelled');
    assert_same('done', $act($alice, 1001, 'reactivate', '2026-12-15', 'req-reactivate')['status'], 'active again');
    $deleted = $act($alice, 1001, 'delete', '2026-12-15', 'req-delete');
    assert_same(['done', []], [$deleted['status'], array_column($deleted['state']['records'], 'id')], 'deleted; the state no longer has it');

    $db->close();
});

wallos_test('settings, unlinking and malformed requests', function () {
    [$db, $alice] = shelflife_webapp_test_setup();
    $handle = fn($request) => shelflife_webapp_handle($db, $alice, 1001, $request, '2026-11-01');

    $saved = $handle(['op' => 'settings', 'request_id' => 'req-days', 'reminder_days' => 3]);
    assert_same(['saved', 3, 3], [$saved['status'], $saved['reminder_days'], $saved['state']['account']['reminder_days']], 'the default reminder is saved');
    assert_same('invalid', $handle(['op' => 'settings', 'request_id' => 'req-days-9', 'reminder_days' => 9])['status'], 'out of range');
    assert_same('invalid', $handle(['op' => 'save', 'record' => ['name' => 'x']])['status'], 'a change needs a request id');
    assert_same('invalid', $handle(['op' => 'drop_tables', 'request_id' => 'req-drop'])['status'], 'unknown operation');
    assert_same('invalid', $handle(['op' => 'unlink', 'request_id' => 'req-unlink-no'])['status'], 'unlinking needs confirmation');
    assert_same(1001, $db->querySingle('SELECT telegram_id FROM user WHERE id = 1'), 'still linked');
    assert_same('unlinked', $handle(['op' => 'unlink', 'request_id' => 'req-unlink', 'confirm' => true])['status'], 'unlinked when confirmed');
    assert_same(null, $db->querySingle('SELECT telegram_id FROM user WHERE id = 1'), 'the link is gone');

    $db->close();
});

wallos_test('another account cannot replay a Mini App request id', function () {
    [$db, $alice, $bob] = shelflife_webapp_test_setup();
    $request = ['op' => 'save', 'request_id' => 'req-shared-id', 'record' => ['name' => 'Private', 'price' => '5',
                'currency_id' => wallos_test_currency_id(1, 0), 'cycle' => 3, 'frequency' => 1, 'next_payment' => '2026-12-01']];

    assert_same('saved', shelflife_webapp_handle($db, $alice, 1001, $request, '2026-11-01')['status'], 'alice saves');
    $replay = shelflife_webapp_handle($db, $bob, 1002, $request, '2026-11-01');
    assert_same(['status' => 'invalid'], $replay, 'bob gets nothing of alice\'s answer');

    $db->close();
});
