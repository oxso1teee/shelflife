<?php
/*
  ShelfLife: who is using the Telegram Mini App.

  Telegram opens the Mini App with "init data": a query string about the user,
  signed with the bot's token. Only that signature proves who the user is —
  never a Telegram id the page sends, nor initDataUnsafe, which any page can
  write. Checked as in https://core.telegram.org/bots/webapps (validating data
  received via the Mini App):

    secret_key       = HMAC-SHA256(key "WebAppData", message bot_token)
    data_check_string = every field except "hash", sorted by name, "key=value",
                        joined with "\n"
    hash             = hex(HMAC-SHA256(key secret_key, message data_check_string))

  auth_date bounds how long one copy of the init data can be used.
*/

const SHELFLIFE_WEBAPP_MAX_AGE = 86400;    // a Mini App left open for a day must be reopened
const SHELFLIFE_WEBAPP_CLOCK_SKEW = 60;    // tolerated future auth_date
const SHELFLIFE_WEBAPP_MAX_LENGTH = 8192;

/**
 * Splits init data into its fields. A field that appears twice makes it invalid.
 *
 * @return array<string, string>|null
 */
function shelflife_webapp_fields($initData)
{
    $fields = [];
    foreach (explode('&', $initData) as $pair) {
        if ($pair === '') {
            continue;
        }
        $parts = explode('=', $pair, 2);
        $key = urldecode($parts[0]);
        if ($key === '' || array_key_exists($key, $fields)) {
            return null;
        }
        $fields[$key] = urldecode($parts[1] ?? '');
    }

    return $fields;
}

/**
 * @param string $initData the raw query string Telegram passed to the Mini App
 * @param string $botToken
 * @param int    $now      Unix time
 * @return array ['ok' => true, 'user' => ['id' => int, 'username' => ?string, 'first_name' => ?string]]
 *             | ['ok' => false, 'reason' => missing|no_bot_token|malformed|missing_hash|bad_hash|bad_auth_date|expired|bad_user]
 */
function shelflife_webapp_verify($initData, $botToken, $now, $maxAge = SHELFLIFE_WEBAPP_MAX_AGE)
{
    $fail = fn($reason) => ['ok' => false, 'reason' => $reason];

    if (!is_string($initData) || $initData === '' || strlen($initData) > SHELFLIFE_WEBAPP_MAX_LENGTH) {
        return $fail('missing');
    }
    if (!is_string($botToken) || $botToken === '') {
        return $fail('no_bot_token');
    }

    $fields = shelflife_webapp_fields($initData);
    if ($fields === null) {
        return $fail('malformed');
    }
    $hash = $fields['hash'] ?? '';
    if (!preg_match('/^[0-9a-f]{64}$/i', $hash)) {
        return $fail('missing_hash');
    }
    unset($fields['hash']);
    ksort($fields, SORT_STRING);

    $lines = [];
    foreach ($fields as $key => $value) {
        $lines[] = $key . '=' . $value;
    }
    $secretKey = hash_hmac('sha256', $botToken, 'WebAppData', true);
    if (!hash_equals(hash_hmac('sha256', implode("\n", $lines), $secretKey), strtolower($hash))) {
        return $fail('bad_hash');
    }

    $authDate = $fields['auth_date'] ?? '';
    if (!ctype_digit($authDate) || (int) $authDate > $now + SHELFLIFE_WEBAPP_CLOCK_SKEW) {
        return $fail('bad_auth_date');
    }
    if ($now - (int) $authDate > $maxAge) {
        return $fail('expired');
    }

    $user = json_decode($fields['user'] ?? '', true);
    if (!is_array($user) || !is_int($user['id'] ?? null) || $user['id'] <= 0) {
        return $fail('bad_user');
    }

    return [
        'ok' => true,
        'user' => [
            'id' => $user['id'],
            'username' => is_string($user['username'] ?? null) ? $user['username'] : null,
            'first_name' => is_string($user['first_name'] ?? null) ? $user['first_name'] : null,
        ],
    ];
}
