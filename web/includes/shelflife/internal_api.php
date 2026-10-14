<?php
/*
  ShelfLife: common entry point of the bot's internal API (api/internal/telegram/*.php).

  The bot is a separate process with no database of its own. Everything it reads
  or changes goes through these endpoints, which call the same functions as the
  web pages, so the rules live in one place.

  Every request must:
  - be a POST with a JSON body;
  - carry the shared service key in the X-ShelfLife-Service-Key header. The key
    comes from SHELFLIFE_SERVICE_KEY (or SHELFLIFE_SERVICE_KEY_FILE) and must be
    at least 32 characters; without one configured, the API refuses everything.

  nginx additionally limits /api/internal/ to the private container networks.
  The caller's Telegram id selects the account; the bot gets it from Telegram's
  update, never from user input.
*/

require_once __DIR__ . '/../instance_config.php';

const SHELFLIFE_SERVICE_KEY_MIN_LENGTH = 32;

/**
 * @return string|null the configured service key, or null when none usable is set
 */
function shelflife_internal_service_key()
{
    $secret = wallos_env_secret('SHELFLIFE_SERVICE_KEY');
    $value = $secret['value'] ?? null;

    if (!is_string($value) || strlen($value) < SHELFLIFE_SERVICE_KEY_MIN_LENGTH) {
        return null;
    }

    return $value;
}

function shelflife_internal_key_matches($provided, $expected)
{
    if (!is_string($expected) || strlen($expected) < SHELFLIFE_SERVICE_KEY_MIN_LENGTH || !is_string($provided)) {
        return false;
    }

    return hash_equals($expected, $provided);
}

function shelflife_internal_respond($status, array $body)
{
    http_response_code($status);
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode($body);
    exit;
}

/**
 * Checks the method and the service key and returns the decoded JSON body.
 * Answers and exits on any failure.
 *
 * @return array
 */
function shelflife_internal_request()
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        shelflife_internal_respond(405, ['error' => 'method_not_allowed']);
    }

    $expected = shelflife_internal_service_key();
    if ($expected === null) {
        error_log('ShelfLife: SHELFLIFE_SERVICE_KEY is not set (or shorter than 32 characters); the internal API is disabled.');
        shelflife_internal_respond(503, ['error' => 'not_configured']);
    }

    if (!shelflife_internal_key_matches($_SERVER['HTTP_X_SHELFLIFE_SERVICE_KEY'] ?? null, $expected)) {
        shelflife_internal_respond(401, ['error' => 'unauthorized']);
    }

    $payload = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($payload)) {
        shelflife_internal_respond(400, ['error' => 'invalid_json']);
    }

    return $payload;
}

/**
 * @return SQLite3
 */
function shelflife_internal_db()
{
    $db = new SQLite3(__DIR__ . '/../../db/wallos.db');
    $db->busyTimeout(5000);

    return $db;
}

/**
 * A positive integer id from the payload, or answers 400 and exits.
 *
 * @return int
 */
function shelflife_internal_int(array $payload, $field)
{
    $value = $payload[$field] ?? null;
    if (!is_int($value) || $value <= 0) {
        shelflife_internal_respond(400, ['error' => 'invalid_' . $field]);
    }

    return $value;
}
