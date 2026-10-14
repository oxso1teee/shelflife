<?php
/*
  ShelfLife: linking a Wallos account to the user's Telegram account.

  The profile page asks for a one-time token and shows it as a t.me deep link
  and a QR code. The bot passes the token back with the user's Telegram id
  through the internal API (api/internal/telegram/link.php).

  - Tokens are 32 hex characters, valid for 15 minutes and usable once. Only a
    SHA-256 hash is stored, so the table is useless to whoever reads it.
  - Issuing a new token voids the user's earlier unused ones.
  - A Telegram account can be linked to one Wallos account. Linking from a
    different Wallos account is refused rather than silently moved.
  - A consumed token is marked used in the same transaction that links the
    account, so a repeated /start with the same token does nothing.
*/

const SHELFLIFE_LINK_TOKEN_TTL = 900;

function shelflife_link_token_hash($token)
{
    return hash('sha256', (string) $token);
}

function shelflife_link_token_is_well_formed($token)
{
    return is_string($token) && preg_match('/^[0-9a-f]{32}$/', $token) === 1;
}

/**
 * @param int $now unix time
 * @return array{token: string, expires_at: int}
 */
function shelflife_link_issue_token(SQLite3 $db, $userId, $now)
{
    $token = bin2hex(random_bytes(16));

    // Voiding the old tokens and storing the new one is one step: a failed
    // delete must not leave two valid tokens behind.
    $db->exec('BEGIN IMMEDIATE');

    $void = $db->prepare('DELETE FROM telegram_link_tokens WHERE user_id = :userId AND used_at IS NULL');
    $void->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    if ($void->execute() === false) {
        $db->exec('ROLLBACK');
        throw new RuntimeException('Failed to void old link tokens: ' . $db->lastErrorMsg());
    }

    $stmt = $db->prepare('INSERT INTO telegram_link_tokens (user_id, token_hash, created_at, expires_at)
                          VALUES (:userId, :hash, :now, :expires)');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->bindValue(':hash', shelflife_link_token_hash($token), SQLITE3_TEXT);
    $stmt->bindValue(':now', (int) $now, SQLITE3_INTEGER);
    $stmt->bindValue(':expires', (int) $now + SHELFLIFE_LINK_TOKEN_TTL, SQLITE3_INTEGER);
    if ($stmt->execute() === false) {
        $db->exec('ROLLBACK');
        throw new RuntimeException('Failed to issue a link token: ' . $db->lastErrorMsg());
    }

    $db->exec('COMMIT');

    return ['token' => $token, 'expires_at' => (int) $now + SHELFLIFE_LINK_TOKEN_TTL];
}

/**
 * Links the account the token was issued for to $telegramId.
 *
 * @param int $now unix time
 * @return array{status: string, user_id: int|null, username: string|null}
 *   status: 'linked' | 'invalid_token' (unknown, expired or already used) | 'telegram_taken'
 */
function shelflife_link_consume(SQLite3 $db, $token, $telegramId, $telegramUsername, $now)
{
    $result = ['status' => 'invalid_token', 'user_id' => null, 'username' => null];
    if (!shelflife_link_token_is_well_formed($token) || (int) $telegramId <= 0) {
        return $result;
    }

    $db->exec('BEGIN IMMEDIATE');
    try {
        $find = $db->prepare('SELECT t.id, t.user_id, u.username FROM telegram_link_tokens t JOIN user u ON u.id = t.user_id
                              WHERE t.token_hash = :hash AND t.used_at IS NULL AND t.expires_at > :now');
        $find->bindValue(':hash', shelflife_link_token_hash($token), SQLITE3_TEXT);
        $find->bindValue(':now', (int) $now, SQLITE3_INTEGER);
        $row = $find->execute()->fetchArray(SQLITE3_ASSOC);

        if ($row === false) {
            $db->exec('ROLLBACK');
            return $result;
        }

        $owner = $db->prepare('SELECT id FROM user WHERE telegram_id = :telegramId AND id != :userId');
        $owner->bindValue(':telegramId', (int) $telegramId, SQLITE3_INTEGER);
        $owner->bindValue(':userId', (int) $row['user_id'], SQLITE3_INTEGER);
        if ($owner->execute()->fetchArray() !== false) {
            // Leave the token unused: the user can unlink the other account and retry.
            $db->exec('ROLLBACK');
            return ['status' => 'telegram_taken', 'user_id' => null, 'username' => null];
        }

        $use = $db->prepare('UPDATE telegram_link_tokens SET used_at = :now WHERE id = :id AND used_at IS NULL');
        $use->bindValue(':now', (int) $now, SQLITE3_INTEGER);
        $use->bindValue(':id', (int) $row['id'], SQLITE3_INTEGER);
        $use->execute();
        if ($db->changes() !== 1) {
            $db->exec('ROLLBACK');
            return $result;
        }

        $link = $db->prepare('UPDATE user SET telegram_id = :telegramId, telegram_username = :telegramUsername WHERE id = :userId');
        $link->bindValue(':telegramId', (int) $telegramId, SQLITE3_INTEGER);
        $link->bindValue(':telegramUsername', $telegramUsername === null || $telegramUsername === '' ? null : (string) $telegramUsername,
            $telegramUsername === null || $telegramUsername === '' ? SQLITE3_NULL : SQLITE3_TEXT);
        $link->bindValue(':userId', (int) $row['user_id'], SQLITE3_INTEGER);
        if ($link->execute() === false) {
            $db->exec('ROLLBACK');
            return ['status' => 'telegram_taken', 'user_id' => null, 'username' => null];
        }

        $db->exec('COMMIT');
    } catch (Throwable $e) {
        $db->exec('ROLLBACK');
        throw $e;
    }

    return ['status' => 'linked', 'user_id' => (int) $row['user_id'], 'username' => $row['username']];
}

function shelflife_link_unlink(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('UPDATE user SET telegram_id = NULL, telegram_username = NULL WHERE id = :userId');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $stmt->execute();

    $void = $db->prepare('DELETE FROM telegram_link_tokens WHERE user_id = :userId AND used_at IS NULL');
    $void->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $void->execute();
}

/**
 * @return array|null id, username, main_currency, language of the linked account
 */
function shelflife_link_find_user(SQLite3 $db, $telegramId)
{
    if ((int) $telegramId <= 0) {
        return null;
    }

    $stmt = $db->prepare('SELECT id, username, main_currency, language, telegram_username FROM user WHERE telegram_id = :telegramId');
    $stmt->bindValue(':telegramId', (int) $telegramId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return $row === false ? null : $row;
}

/**
 * @return array{linked: bool, telegram_username: string|null}
 */
function shelflife_link_status(SQLite3 $db, $userId)
{
    $stmt = $db->prepare('SELECT telegram_id, telegram_username FROM user WHERE id = :userId');
    $stmt->bindValue(':userId', (int) $userId, SQLITE3_INTEGER);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    return [
        'linked' => $row !== false && $row['telegram_id'] !== null,
        'telegram_username' => $row === false ? null : $row['telegram_username'],
    ];
}
