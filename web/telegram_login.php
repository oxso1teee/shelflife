<?php
/*
  ShelfLife: sign in with the Telegram Login Widget.

  The widget on login.php sends the user here (data-auth-url) with Telegram's
  signed data. Signing in follows the same rules as the password form:
  - the signature and its age are checked (includes/shelflife/telegram_auth.php);
  - only a Telegram account already linked on the profile page can sign in —
    nobody gets an account just by having Telegram;
  - an installation set to sign in through its identity provider only (SSO)
    refuses this the way it refuses passwords;
  - an unverified email and two-factor authentication are handled by the same
    code as the password login (includes/shelflife/session.php).
*/

require_once 'includes/connect.php';
require_once 'includes/oidc_settings.php';
require_once 'includes/instance_config.php';
require_once 'includes/shelflife/telegram_auth.php';
require_once 'includes/shelflife/telegram_link.php';
require_once 'includes/shelflife/session.php';

$secondsInMonth = 30 * 24 * 60 * 60;
if (session_status() === PHP_SESSION_NONE) {
    session_set_cookie_params([
        'lifetime' => $secondsInMonth,
        'httponly' => true,
        'samesite' => 'Lax'
    ]);
    session_start();
}

function shelflife_telegram_login_fail(SQLite3 $db, $error)
{
    $db->close();
    header('Location: login.php?error=' . $error);
    exit();
}

$oidcConfiguration = wallos_get_effective_oidc_configuration($db);
$ssoOnly = $oidcConfiguration['enabled'] == 1 && $oidcConfiguration['is_configured']
    && (int) ($oidcConfiguration['settings']['password_login_disabled'] ?? 0) === 1;
$botToken = wallos_env_secret('TELEGRAM_BOT_TOKEN')['value'] ?? null;
if ($ssoOnly || !is_string($botToken) || $botToken === '') {
    shelflife_telegram_login_fail($db, 'telegram_login_disabled');
}

$check = shelflife_telegram_auth_verify($_GET, $botToken, time());
if (!$check['ok']) {
    shelflife_telegram_login_fail($db, 'telegram_auth_failed');
}

$user = shelflife_link_find_user($db, $check['telegram_id']);
if ($user === null) {
    shelflife_telegram_login_fail($db, 'telegram_not_linked');
}

$result = shelflife_complete_login($db, (int) $user['id'], $user['username'], $user['main_currency'], $user['language'] ?: 'en', false);
if ($result === 'unverified') {
    shelflife_telegram_login_fail($db, 'telegram_email_not_verified');
}

$db->close();
header('Location: ' . ($result === 'totp' ? 'totp.php' : '.'));
exit();
