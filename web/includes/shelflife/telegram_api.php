<?php
/*
  ShelfLife: a minimal Telegram Bot API client for sending reminders.

  Wallos already talks to api.telegram.org with curl for its own Telegram
  channel (endpoints/cronjobs/sendnotifications.php) but only checks whether
  curl failed. This one reads Telegram's answer, so the caller can tell a
  delivered message from flood control (429, retry_after), a user who blocked
  the bot (403) or a malformed message (400). The token is never logged.
*/

/**
 * @param string $token  bot token
 * @param string $method Bot API method, e.g. sendMessage
 * @return array{ok: bool, result: mixed, error_code: int|null, description: string|null,
 *               retry_after: int|null, network_error: string|null}
 */
function shelflife_telegram_call($token, $method, array $payload, $timeout = 15)
{
    $answer = ['ok' => false, 'result' => null, 'error_code' => null, 'description' => null, 'retry_after' => null, 'network_error' => null];

    $body = json_encode($payload);
    $ch = curl_init('https://api.telegram.org/bot' . $token . '/' . $method);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Content-Length: ' . strlen($body)],
    ]);
    $raw = curl_exec($ch);

    if ($raw === false) {
        $answer['network_error'] = curl_error($ch) ?: 'request failed';
        return $answer;
    }

    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        $answer['network_error'] = 'unreadable answer (HTTP ' . curl_getinfo($ch, CURLINFO_HTTP_CODE) . ')';
        return $answer;
    }

    $answer['ok'] = ($decoded['ok'] ?? false) === true;
    $answer['result'] = $decoded['result'] ?? null;
    $answer['error_code'] = isset($decoded['error_code']) ? (int) $decoded['error_code'] : null;
    $answer['description'] = isset($decoded['description']) ? (string) $decoded['description'] : null;
    $answer['retry_after'] = isset($decoded['parameters']['retry_after']) ? (int) $decoded['parameters']['retry_after'] : null;

    return $answer;
}

/**
 * A sender for includes/shelflife/notifications.php: fn($chatId, $text, $replyMarkup) => answer.
 *
 * @return callable
 */
function shelflife_telegram_sender($token)
{
    return function ($chatId, $text, array $replyMarkup) use ($token) {
        return shelflife_telegram_call($token, 'sendMessage', [
            'chat_id' => $chatId,
            'text' => $text,
            'parse_mode' => 'HTML',
            'reply_markup' => $replyMarkup,
            'link_preview_options' => ['is_disabled' => true],
        ]);
    };
}
