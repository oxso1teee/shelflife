<?php
/*
  ShelfLife Telegram Login Widget check (includes/shelflife/telegram_auth.php)
  and the order of steps in telegram_login.php.

  The widget data is signed here the way Telegram documents it, with a test
  token; any changed field, a different token, a missing hash or stale data
  must be refused.
*/

require_once WALLOS_ROOT . '/includes/shelflife/telegram_auth.php';

const SHELFLIFE_TEST_BOT_TOKEN = '123456:TEST-token-for-the-widget';

function shelflife_test_widget_data(array $fields, $token = SHELFLIFE_TEST_BOT_TOKEN)
{
    $fields = array_map('strval', $fields);
    $fields['hash'] = hash_hmac('sha256', shelflife_telegram_auth_check_string($fields), hash('sha256', $token, true));

    return $fields;
}

wallos_test('the data-check-string is the sorted fields without the hash', function () {
    assert_same("auth_date=100\nfirst_name=Ann\nid=5", shelflife_telegram_auth_check_string(['id' => 5, 'hash' => 'x', 'first_name' => 'Ann', 'auth_date' => 100]), 'sorted, joined with newlines');
});

wallos_test('correctly signed, fresh data is accepted', function () {
    $now = 1_800_000_000;
    $data = shelflife_test_widget_data(['id' => 555, 'first_name' => 'Ольга', 'username' => 'olga_tg', 'auth_date' => $now - 30]);

    assert_same(['ok' => true, 'reason' => null, 'telegram_id' => 555, 'username' => 'olga_tg'], shelflife_telegram_auth_verify($data, SHELFLIFE_TEST_BOT_TOKEN, $now), 'accepted');
});

wallos_test('changed, foreign, missing or stale data is refused', function () {
    $now = 1_800_000_000;
    $data = shelflife_test_widget_data(['id' => 555, 'first_name' => 'Ann', 'auth_date' => $now - 30]);

    $reason = fn($d, $token = SHELFLIFE_TEST_BOT_TOKEN, $at = null) => shelflife_telegram_auth_verify($d, $token, $at ?? $now)['reason'];

    assert_same('bad_hash', $reason(['id' => '777'] + $data), 'another user id');
    assert_same('bad_hash', $reason($data + ['extra' => 'x']), 'an added field');
    assert_same('bad_hash', $reason($data, 'other:token'), 'signed for another bot');
    assert_same('missing_hash', $reason(array_diff_key($data, ['hash' => 1])), 'no hash');
    assert_same('missing_hash', $reason(['hash' => 'not-hex'] + $data), 'malformed hash');
    assert_same('expired', $reason($data, SHELFLIFE_TEST_BOT_TOKEN, $now + SHELFLIFE_TELEGRAM_AUTH_MAX_AGE), 'too old');
    assert_same('bad_auth_date', $reason(shelflife_test_widget_data(['id' => 5, 'auth_date' => $now + 3600])), 'from the future');
    assert_same('bad_id', $reason(shelflife_test_widget_data(['id' => 0, 'auth_date' => $now])), 'no user id');
    assert_same('no_bot_token', $reason($data, ''), 'no bot configured');
});

wallos_test('the widget login checks the signature, then the link, then signs in like the password form', function () {
    $source = file_get_contents(WALLOS_ROOT . '/telegram_login.php');

    $positions = array_map(fn($needle) => strpos($source, $needle), [
        "'password_login_disabled'",
        'shelflife_telegram_auth_verify(',
        'shelflife_link_find_user(',
        'shelflife_complete_login(',
    ]);
    assert_true(!in_array(false, $positions, true), 'every step is there');
    for ($i = 1; $i < count($positions); $i++) {
        assert_true($positions[$i - 1] < $positions[$i], 'step ' . $i . ' comes after step ' . ($i - 1));
    }

    $login = file_get_contents(WALLOS_ROOT . '/login.php');
    assert_contains('shelflife_complete_login(', $login, 'the password form signs in through the same function');
});
