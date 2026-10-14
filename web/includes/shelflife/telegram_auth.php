<?php
/*
  ShelfLife: checking the data the Telegram Login Widget sends back.

  Telegram's documentation (core.telegram.org/widgets/login-legacy): the
  data-check-string is every received field except "hash", sorted by name, as
  "name=value" lines joined with "\n"; the expected hash is the hex HMAC-SHA-256
  of that string keyed with the SHA-256 of the bot token. auth_date is checked
  as well, so captured login data cannot be replayed later.
*/

const SHELFLIFE_TELEGRAM_AUTH_MAX_AGE = 600;   // seconds a widget login stays valid
const SHELFLIFE_TELEGRAM_AUTH_CLOCK_SKEW = 60;  // tolerated future auth_date

function shelflife_telegram_auth_check_string(array $data)
{
    $fields = [];
    foreach ($data as $name => $value) {
        if ($name === 'hash' || !is_scalar($value)) {
            continue;
        }
        $fields[(string) $name] = (string) $value;
    }
    ksort($fields, SORT_STRING);

    $lines = [];
    foreach ($fields as $name => $value) {
        $lines[] = $name . '=' . $value;
    }

    return implode("\n", $lines);
}

/**
 * @param array  $data     the widget's query parameters
 * @param string $botToken the token of the bot the widget belongs to
 * @param int    $now      unix time
 * @return array{ok: bool, reason: string|null, telegram_id: int|null, username: string|null}
 */
function shelflife_telegram_auth_verify(array $data, $botToken, $now)
{
    $fail = fn($reason) => ['ok' => false, 'reason' => $reason, 'telegram_id' => null, 'username' => null];

    $hash = $data['hash'] ?? null;
    if (!is_string($hash) || !preg_match('/^[0-9a-f]{64}$/i', $hash)) {
        return $fail('missing_hash');
    }
    if (!is_string($botToken) || $botToken === '') {
        return $fail('no_bot_token');
    }

    $secret = hash('sha256', $botToken, true);
    $expected = hash_hmac('sha256', shelflife_telegram_auth_check_string($data), $secret);
    if (!hash_equals($expected, strtolower($hash))) {
        return $fail('bad_hash');
    }

    $authDate = $data['auth_date'] ?? null;
    if (!(is_string($authDate) || is_int($authDate)) || !ctype_digit((string) $authDate)) {
        return $fail('bad_auth_date');
    }
    $authDate = (int) $authDate;
    if ($now - $authDate > SHELFLIFE_TELEGRAM_AUTH_MAX_AGE) {
        return $fail('expired');
    }
    if ($authDate - $now > SHELFLIFE_TELEGRAM_AUTH_CLOCK_SKEW) {
        return $fail('bad_auth_date');
    }

    $id = $data['id'] ?? null;
    if (!(is_string($id) || is_int($id)) || !ctype_digit((string) $id) || (int) $id <= 0) {
        return $fail('bad_id');
    }

    $username = $data['username'] ?? null;

    return [
        'ok' => true,
        'reason' => null,
        'telegram_id' => (int) $id,
        'username' => is_string($username) && preg_match('/^[A-Za-z0-9_]{1,64}$/', $username) ? $username : null,
    ];
}
