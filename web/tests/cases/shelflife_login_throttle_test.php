<?php
/*
  ShelfLife login throttling (includes/shelflife/login_throttle.php).

  Five wrong passwords within 15 minutes lock that username until the oldest of
  them is 15 minutes old. A correct password clears the count. The login page
  has to consult the throttle before it checks the password.
*/

require_once WALLOS_ROOT . '/includes/shelflife/login_throttle.php';

wallos_test('five failures lock the username, other usernames stay open', function () {
    $db = wallos_test_open_database();
    $now = 1_800_000_000;

    for ($i = 0; $i < 4; $i++) {
        shelflife_login_record_failure($db, 'alice', $now + $i);
    }
    assert_same(false, shelflife_login_is_throttled($db, 'alice', $now + 10), 'four failures are allowed');

    shelflife_login_record_failure($db, 'alice', $now + 4);
    assert_same(true, shelflife_login_is_throttled($db, 'alice', $now + 10), 'the fifth failure locks');
    assert_same(true, shelflife_login_is_throttled($db, ' ALICE ', $now + 10), 'case and spaces do not reset the count');
    assert_same(false, shelflife_login_is_throttled($db, 'bob', $now + 10), 'other usernames are not affected');

    $db->close();
});

wallos_test('the lock ends when the oldest counted failure leaves the window', function () {
    $db = wallos_test_open_database();
    $now = 1_800_000_000;

    for ($i = 0; $i < 5; $i++) {
        shelflife_login_record_failure($db, 'alice', $now + 60 * $i);
    }

    assert_same($now + SHELFLIFE_LOGIN_WINDOW_SECONDS, shelflife_login_blocked_until($db, 'alice', $now + 300), 'locked until the first failure expires');
    assert_same(true, shelflife_login_is_throttled($db, 'alice', $now + SHELFLIFE_LOGIN_WINDOW_SECONDS - 1), 'still locked a second before');
    assert_same(false, shelflife_login_is_throttled($db, 'alice', $now + SHELFLIFE_LOGIN_WINDOW_SECONDS + 1), 'open again afterwards');

    $db->close();
});

wallos_test('a correct password clears the failures', function () {
    $db = wallos_test_open_database();
    $now = 1_800_000_000;

    for ($i = 0; $i < 4; $i++) {
        shelflife_login_record_failure($db, 'alice', $now + $i);
    }
    shelflife_login_clear_failures($db, 'Alice');
    shelflife_login_record_failure($db, 'alice', $now + 10);

    assert_same(false, shelflife_login_is_throttled($db, 'alice', $now + 11), 'counting starts over');

    $db->close();
});

wallos_test('the login page checks the throttle before the password and records failures', function () {
    $source = file_get_contents(WALLOS_ROOT . '/login.php');

    $throttle = strpos($source, 'shelflife_login_is_throttled(');
    $verify = strpos($source, 'password_verify(');
    assert_true($throttle !== false && $verify !== false && $throttle < $verify, 'the throttle is consulted before password_verify()');
    assert_same(2, substr_count($source, 'shelflife_login_record_failure('), 'both failure branches record the attempt');
    assert_contains('shelflife_login_clear_failures(', $source, 'a correct password clears the count');
});
