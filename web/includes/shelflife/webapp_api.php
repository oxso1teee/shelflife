<?php
/*
  ShelfLife: what the Telegram Mini App can do, on behalf of the linked
  account behind verified init data (webapp_auth.php). The endpoint is
  api/tma/app.php; this file holds the operations so they can be tested.

  Every change goes through the services the website and the bot use
  (subscription_service.php, bot_actions.php, overview.php), and every answer
  carries the account's fresh state, so the Mini App shows exactly what the
  website shows. A request_id makes a create, an action or a setting apply
  once even if the request is sent twice (shelflife_bot_once(), keyed per
  Telegram account).

  Operations (JSON body, "op"):
    state                                  -> the account's overview
    save     {request_id, record: {...}}   -> create (no id) or edit (id) a record
    act      {request_id, id, action, expected_due}
                                           -> renew | cancel | snooze | reactivate | delete
    settings {request_id, reminder_days}   -> the account's default reminder (0-7 days)
    unlink   {request_id, confirm: true}   -> unlink this Telegram account
*/

require_once __DIR__ . '/overview.php';
require_once __DIR__ . '/bot_actions.php';

// Fields the Mini App form may set; everything else keeps its stored value.
const SHELFLIFE_WEBAPP_RECORD_FIELDS = ['kind', 'name', 'price', 'currency_id', 'cycle', 'frequency', 'next_payment',
                                        'category_id', 'notify', 'notify_days_before', 'auto_renew'];

/**
 * The bot-update id that stands for a Mini App request in shelflife_bot_once():
 * negative, so it never meets a real Telegram update id.
 *
 * @return int|null null for a missing or malformed request_id
 */
function shelflife_webapp_request_key($requestId)
{
    if (!is_string($requestId) || !preg_match('/^[A-Za-z0-9_-]{8,64}$/', $requestId)) {
        return null;
    }

    return -1 - (int) hexdec(substr(hash('sha256', 'tma:' . $requestId), 0, 13));
}

function shelflife_webapp_state(SQLite3 $db, array $user, $today, array $extra = [])
{
    return $extra + ['status' => 'ok', 'state' => shelflife_overview($db, (int) $user['id'], $today)];
}

/**
 * Creates or edits a record with the website's validation.
 */
function shelflife_webapp_save(SQLite3 $db, array $user, array $record, $today)
{
    $userId = (int) $user['id'];
    $input = array_intersect_key($record, array_flip(SHELFLIFE_WEBAPP_RECORD_FIELDS));
    foreach ($input as $key => $value) {
        if (is_float($value)) {
            $input[$key] = (string) $value;
        }
    }

    try {
        if (isset($record['id'])) {
            $existing = shelflife_subscription_find($db, $userId, (int) $record['id']);
            if ($existing === null) {
                return ['status' => 'not_found'];
            }
            $data = shelflife_subscription_prepare($db, $userId, $input, $existing);
            shelflife_subscription_update($db, $userId, (int) $existing['id'], $data);
            return ['status' => 'saved', 'id' => (int) $existing['id']];
        }

        $input += [
            'start_date' => $today,
            'auto_renew' => false,
            'notify' => true,
            'notify_days_before' => -1,
            'payer_user_id' => shelflife_bot_default_id($db, 'household', $userId),
            'payment_method_id' => shelflife_bot_default_id($db, 'payment_methods', $userId),
        ];
        if (!array_key_exists('category_id', $input)) {
            $input['category_id'] = shelflife_bot_default_id($db, 'categories', $userId);
        }
        $data = shelflife_subscription_prepare($db, $userId, $input);
        return ['status' => 'saved', 'id' => shelflife_subscription_insert($db, $userId, $data)];
    } catch (ShelfLifeValidationError $e) {
        return ['status' => 'invalid', 'field' => $e->field, 'message' => $e->getMessage()];
    }
}

/**
 * One Mini App request.
 *
 * @param array  $user       the linked account (shelflife_link_find_user())
 * @param int    $telegramId from verified init data
 * @param array  $request    the decoded JSON body
 * @param string $today      Y-m-d
 * @return array the JSON answer
 */
function shelflife_webapp_handle(SQLite3 $db, array $user, $telegramId, array $request, $today)
{
    $op = $request['op'] ?? 'state';
    if ($op === 'state') {
        return shelflife_webapp_state($db, $user, $today);
    }

    $key = shelflife_webapp_request_key($request['request_id'] ?? null);
    if ($key === null) {
        return ['status' => 'invalid', 'field' => 'request_id', 'message' => 'A request id is required.'];
    }

    switch ($op) {
        case 'save':
            if (!is_array($request['record'] ?? null)) {
                return ['status' => 'invalid', 'field' => 'record', 'message' => 'The record is missing.'];
            }
            $action = fn() => shelflife_webapp_save($db, $user, $request['record'], $today);
            break;
        case 'act':
            $payload = ['subscription_id' => (int) ($request['id'] ?? 0), 'action' => $request['action'] ?? null, 'expected_due' => $request['expected_due'] ?? null];
            $action = fn() => shelflife_bot_act($db, $user, $payload, $today);
            break;
        case 'settings':
            $action = function () use ($db, $user, $request) {
                try {
                    return ['status' => 'saved', 'reminder_days' => shelflife_set_reminder_days($db, (int) $user['id'], $request['reminder_days'] ?? null)];
                } catch (ShelfLifeValidationError $e) {
                    return ['status' => 'invalid', 'field' => $e->field, 'message' => $e->getMessage()];
                }
            };
            break;
        case 'unlink':
            if (($request['confirm'] ?? false) !== true) {
                return ['status' => 'invalid', 'field' => 'confirm', 'message' => 'Unlinking must be confirmed.'];
            }
            $action = function () use ($db, $user) {
                shelflife_link_unlink($db, (int) $user['id']);
                return ['status' => 'unlinked'];
            };
            break;
        default:
            return ['status' => 'invalid', 'field' => 'op', 'message' => 'Unknown operation.'];
    }

    $result = shelflife_bot_once($db, $key, $telegramId, $action);
    unset($result['repeated']);
    if (in_array($result['status'] ?? null, ['unlinked', 'invalid'], true)) {
        return $result;
    }

    // A record the action no longer finds belongs to nobody we can show.
    unset($result['record']);
    return shelflife_webapp_state($db, $user, $today, $result);
}
