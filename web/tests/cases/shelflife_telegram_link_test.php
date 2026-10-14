<?php
/*
  ShelfLife Telegram linking (includes/shelflife/telegram_link.php) and the
  service key check of the bot's internal API (includes/shelflife/internal_api.php).

  A token links once, for 15 minutes, and only its hash is stored. A Telegram
  account belongs to one Wallos account at a time.
*/

require_once WALLOS_ROOT . '/includes/shelflife/telegram_link.php';
require_once WALLOS_ROOT . '/includes/shelflife/internal_api.php';

wallos_test('a token links the account once and is stored only as a hash', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $now = 1_800_000_000;

    $issued = shelflife_link_issue_token($db, 1, $now);
    assert_true(shelflife_link_token_is_well_formed($issued['token']), 'the token is 32 hex characters');
    assert_same($now + 900, $issued['expires_at'], 'valid for 15 minutes');
    assert_same(0, $db->querySingle("SELECT COUNT(*) FROM telegram_link_tokens WHERE token_hash = '" . $issued['token'] . "'"), 'the plain token is not stored');

    $first = shelflife_link_consume($db, $issued['token'], 555, 'alice_tg', $now + 60);
    assert_same('linked', $first['status'], 'first use links');
    assert_same(1, $first['user_id'], 'to the account the token was issued for');
    assert_same(['linked' => true, 'telegram_username' => 'alice_tg'], shelflife_link_status($db, 1), 'the profile shows the link');
    assert_same(1, shelflife_link_find_user($db, 555)['id'], 'the bot finds the account by Telegram id');

    $again = shelflife_link_consume($db, $issued['token'], 555, 'alice_tg', $now + 61);
    assert_same('invalid_token', $again['status'], 'a second /start with the same token does nothing');

    $db->close();
});

wallos_test('expired, unknown and malformed tokens are refused', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $now = 1_800_000_000;

    $issued = shelflife_link_issue_token($db, 1, $now);
    assert_same('invalid_token', shelflife_link_consume($db, $issued['token'], 555, null, $now + 900)['status'], 'expired at 15 minutes');
    assert_same('invalid_token', shelflife_link_consume($db, str_repeat('a', 32), 555, null, $now)['status'], 'unknown token');
    assert_same('invalid_token', shelflife_link_consume($db, "' OR 1=1 --", 555, null, $now)['status'], 'malformed token');
    assert_same('invalid_token', shelflife_link_consume($db, $issued['token'], 0, null, $now)['status'], 'no Telegram id');
    assert_same(['linked' => false, 'telegram_username' => null], shelflife_link_status($db, 1), 'nothing was linked');

    $db->close();
});

wallos_test('a new token voids the previous unused one', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $now = 1_800_000_000;

    $old = shelflife_link_issue_token($db, 1, $now);
    $new = shelflife_link_issue_token($db, 1, $now + 10);

    assert_same('invalid_token', shelflife_link_consume($db, $old['token'], 555, null, $now + 20)['status'], 'the old token no longer works');
    assert_same('linked', shelflife_link_consume($db, $new['token'], 555, null, $now + 20)['status'], 'the new one does');

    $db->close();
});

wallos_test('a Telegram account linked elsewhere is not moved silently', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    wallos_test_create_user($db, 2, 'bob');
    $now = 1_800_000_000;

    shelflife_link_consume($db, shelflife_link_issue_token($db, 1, $now)['token'], 555, null, $now);
    $bobToken = shelflife_link_issue_token($db, 2, $now)['token'];

    assert_same('telegram_taken', shelflife_link_consume($db, $bobToken, 555, null, $now + 1)['status'], 'bob cannot take alice\'s Telegram account');
    assert_same(1, shelflife_link_find_user($db, 555)['id'], 'it stays with alice');

    shelflife_link_unlink($db, 1);
    assert_same(null, shelflife_link_find_user($db, 555), 'after alice unlinks');
    assert_same('linked', shelflife_link_consume($db, $bobToken, 555, null, $now + 2)['status'], 'bob\'s unused token now works');

    $db->close();
});

wallos_test('relinking the same account to a new Telegram account replaces the old link', function () {
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $now = 1_800_000_000;

    shelflife_link_consume($db, shelflife_link_issue_token($db, 1, $now)['token'], 555, null, $now);
    shelflife_link_consume($db, shelflife_link_issue_token($db, 1, $now)['token'], 777, null, $now);

    assert_same(null, shelflife_link_find_user($db, 555), 'the old Telegram account is released');
    assert_same(1, shelflife_link_find_user($db, 777)['id'], 'the new one is linked');

    $db->close();
});

wallos_test('the internal API accepts only the configured service key', function () {
    $key = str_repeat('k', 40);

    assert_same(true, shelflife_internal_key_matches($key, $key), 'the right key');
    assert_same(false, shelflife_internal_key_matches($key . 'x', $key), 'a wrong key');
    assert_same(false, shelflife_internal_key_matches(null, $key), 'no header');
    assert_same(false, shelflife_internal_key_matches('', ''), 'an empty key is never a match');
    assert_same(false, shelflife_internal_key_matches('short', 'short'), 'a key under 32 characters is refused');
});

wallos_test('every internal endpoint authenticates before it reads anything', function () {
    $files = glob(WALLOS_ROOT . '/api/internal/telegram/*.php');
    assert_true(count($files) >= 2, 'the internal endpoints were found');

    foreach ($files as $file) {
        $source = file_get_contents($file);
        $auth = strpos($source, 'shelflife_internal_request()');
        $db = strpos($source, 'shelflife_internal_db()');
        assert_true($auth !== false && ($db === false || $auth < $db), basename($file) . ' checks the service key before opening the database');
    }
});
