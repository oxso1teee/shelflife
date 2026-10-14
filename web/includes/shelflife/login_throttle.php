<?php
/*
  ShelfLife: limits password guessing on the login form.

  After SHELFLIFE_LOGIN_MAX_FAILURES wrong passwords for one username within
  SHELFLIFE_LOGIN_WINDOW_SECONDS, further attempts for that username are refused
  without checking the password until the oldest of those failures leaves the
  window. Usernames are compared case-insensitively here, so changing the case
  does not reset the count. The count is per username rather than per address:
  behind the reverse proxy every request comes from the same address.

  The table is created by migrations/000061.php.
*/

const SHELFLIFE_LOGIN_MAX_FAILURES = 5;
const SHELFLIFE_LOGIN_WINDOW_SECONDS = 900;

function shelflife_login_key($username)
{
    return mb_strtolower(trim((string) $username));
}

/**
 * @param int $now unix time
 * @return int|null unix time when attempts are accepted again, or null if they are now
 */
function shelflife_login_blocked_until(SQLite3 $db, $username, $now)
{
    $stmt = $db->prepare('SELECT attempted_at FROM login_attempts WHERE username = :username AND attempted_at > :since
                          ORDER BY attempted_at DESC LIMIT :max');
    $stmt->bindValue(':username', shelflife_login_key($username), SQLITE3_TEXT);
    $stmt->bindValue(':since', $now - SHELFLIFE_LOGIN_WINDOW_SECONDS, SQLITE3_INTEGER);
    $stmt->bindValue(':max', SHELFLIFE_LOGIN_MAX_FAILURES, SQLITE3_INTEGER);
    $result = $stmt->execute();

    $failures = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $failures[] = (int) $row['attempted_at'];
    }

    if (count($failures) < SHELFLIFE_LOGIN_MAX_FAILURES) {
        return null;
    }

    return end($failures) + SHELFLIFE_LOGIN_WINDOW_SECONDS;
}

function shelflife_login_is_throttled(SQLite3 $db, $username, $now)
{
    return shelflife_login_blocked_until($db, $username, $now) !== null;
}

function shelflife_login_record_failure(SQLite3 $db, $username, $now)
{
    $stmt = $db->prepare('INSERT INTO login_attempts (username, attempted_at) VALUES (:username, :at)');
    $stmt->bindValue(':username', shelflife_login_key($username), SQLITE3_TEXT);
    $stmt->bindValue(':at', $now, SQLITE3_INTEGER);
    $stmt->execute();

    // Old rows no longer count for anything.
    $purge = $db->prepare('DELETE FROM login_attempts WHERE attempted_at < :before');
    $purge->bindValue(':before', $now - 86400, SQLITE3_INTEGER);
    $purge->execute();
}

function shelflife_login_clear_failures(SQLite3 $db, $username)
{
    $stmt = $db->prepare('DELETE FROM login_attempts WHERE username = :username');
    $stmt->bindValue(':username', shelflife_login_key($username), SQLITE3_TEXT);
    $stmt->execute();
}
