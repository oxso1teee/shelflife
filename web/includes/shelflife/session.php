<?php
/*
  ShelfLife: signing a user in once their identity has been checked.

  These are the steps Wallos's password login (login.php) takes after a correct
  password, moved here unchanged so the Telegram login (telegram_login.php) signs
  in exactly the same way: an unverified email blocks the sign-in, an account
  with two-factor authentication continues at totp.php, everything else gets a
  fresh session, the optional remember-me cookie and the preference cookies.
*/

/**
 * @param bool $rememberMe set the 30-day remember-me cookie
 * @return string 'unverified' (nothing was done), 'totp' (redirect to totp.php) or 'signed_in'
 */
function shelflife_complete_login(SQLite3 $db, $userId, $username, $mainCurrency, $language, $rememberMe)
{
    $cookieExpire = time() + (30 * 24 * 60 * 60);

    // Check if the user is in the email_verification table
    $stmt = $db->prepare('SELECT 1 FROM email_verification WHERE user_id = :userId');
    $stmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
    if ($stmt->execute()->fetchArray(SQLITE3_ASSOC)) {
        return 'unverified';
    }

    // Check if the user has 2fa enabled
    $stmt = $db->prepare('SELECT totp_enabled FROM user WHERE id = :userId');
    $stmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
    $totpEnabled = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($totpEnabled && $totpEnabled['totp_enabled'] == 1) {
        $_SESSION['totp_user_id'] = $userId;
        if ($rememberMe) {
            $_SESSION['pending_remember_me'] = true; // defer cookie until TOTP done
        }
        return 'totp';
    }

    // No TOTP — safe to create remember-me token now
    if ($rememberMe) {
        $token = bin2hex(random_bytes(32));
        $addLoginTokensStmt = $db->prepare('INSERT INTO login_tokens (user_id, token) VALUES (:userId, :token)');
        $addLoginTokensStmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
        $addLoginTokensStmt->bindValue(':token', $token, SQLITE3_TEXT);
        $addLoginTokensStmt->execute();
        $_SESSION['token'] = $token;
        setcookie('wallos_login', $username . '|' . $token . '|' . $mainCurrency, [
            'expires' => $cookieExpire,
            'samesite' => 'Lax',
            'httponly' => true,
        ]);
    }

    session_regenerate_id(true);
    $_SESSION['username'] = $username;
    $_SESSION['loggedin'] = true;
    $_SESSION['main_currency'] = $mainCurrency;
    $_SESSION['userId'] = $userId;
    setcookie('language', $language, [
        'expires' => $cookieExpire,
        'samesite' => 'Lax'
    ]);

    if (!isset($_COOKIE['sortOrder'])) {
        setcookie('sortOrder', 'next_payment', [
            'expires' => $cookieExpire,
            'samesite' => 'Lax'
        ]);
    }

    $stmt = $db->prepare('SELECT color_theme FROM settings WHERE user_id = :userId');
    $stmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
    $settings = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    setcookie('colorTheme', $settings['color_theme'] ?? '', [
        'expires' => $cookieExpire,
        'samesite' => 'Lax'
    ]);

    return 'signed_in';
}
