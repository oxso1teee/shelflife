<?php
/*
This API Endpoint accepts POST requests only.
It receives the following parameters:
- api_key: the API key of the user (for Wallos authentication).
- action: the action to perform ('add', 'edit', 'delete').
- id / subscription_id: (required for 'edit' and 'delete') the ID of the subscription.

For 'add' and 'edit' actions (all optional for 'edit'):
- name: the name of the subscription.
- price: the price of the subscription (float).
- currency_id: the currency ID of the subscription (integer).
- frequency: the payment frequency (integer).
- cycle: the payment cycle (integer: 1-days, 2-weeks, 3-months, 4-years, 5-one-time).
- kind: what the record tracks: "subscription" (default), "expiry" or "maintenance".
  Only subscriptions require a price; a one-time record needs no frequency.
- next_payment: the next payment date (YYYY-MM-DD).
- start_date: the start date of the subscription (YYYY-MM-DD).
- auto_renew: whether the subscription auto renews (1 or 0, default 1).
- payment_method_id: the payment method ID (integer).
- payer_user_id: the household member payer ID (integer).
- category_id: the category ID (integer).
- notes: subscription notes (string, Markdown supported).
- url: subscription URL (string).
- logo_url: an image URL to download as the logo (string).
- logo: direct image file upload for the logo.
- notify / notifications: whether to send payment notifications (1 or 0).
- notify_days_before: how many days before to send notification (integer).
- inactive: whether the subscription is inactive (1 or 0).
- cancellation_date: the cancellation date (YYYY-MM-DD).
- replacement_subscription_id: the ID of the replacement subscription (integer).

It returns a JSON object with the following properties:
- success: whether the request was successful (boolean).
- title: the title of the response (string).
- message: detailed information or error message (string).
- subscriptionId: (only for successful 'add' action) the ID of the newly created subscription (integer).
- logo_warning: (optional) present when logo_url/logo was given but saving it failed; the subscription is still saved without changing its logo (string).

Example response:
{
  "success": true,
  "title": "Subscription added",
  "subscriptionId": 55,
  "message": "Subscription added successfully."
}
*/

error_reporting(E_ERROR | E_PARSE);
require_once '../../includes/connect_endpoint.php';
require_once '../../includes/inputvalidation.php';
require_once '../../includes/ssrf_helper.php';
require_once '../../includes/logo_theme_variant.php';

header('Content-Type: application/json; charset=UTF-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    echo json_encode([
        'success' => false,
        'title' => 'Invalid request method',
        'message' => 'Only POST requests are allowed.'
    ]);
    exit;
}

$apiKey = $_POST['api_key'] ?? $_POST['apiKey'] ?? null;

// Authenticate user first
if (!$apiKey) {
    echo json_encode([
        'success' => false,
        'title' => 'Missing API key',
        'message' => 'API key is required.'
    ]);
    exit;
}

$sql = "SELECT * FROM user WHERE api_key = :apiKey";
$stmt = $db->prepare($sql);
$stmt->bindValue(':apiKey', $apiKey, SQLITE3_TEXT);
$result = $stmt->execute();
$user = $result->fetchArray(SQLITE3_ASSOC);

if (!$user) {
    echo json_encode([
        'success' => false,
        'title' => 'Unauthorized',
        'message' => 'Invalid API key.'
    ]);
    exit;
}

$userId = $user['id'];
$action = $_POST['action'] ?? null;

if (!$action || !in_array($action, ['add', 'edit', 'delete'], true)) {
    echo json_encode([
        'success' => false,
        'title' => 'Invalid action',
        'message' => 'Action must be "add", "edit", or "delete".'
    ]);
    exit;
}

// Load user settings now that user is authenticated
require_once '../../includes/getsettings.php';

$removeBackgroundEnabled = isset($settings['removeBackground']) && $settings['removeBackground'] === 'true';

if (!file_exists('../../images/uploads/logos')) {
    mkdir('../../images/uploads/logos', 0777, true);
    mkdir('../../images/uploads/logos/avatars', 0777, true);
}

// Image Helper Functions
function sanitizeFilename($filename)
{
    $filename = preg_replace("/[^a-zA-Z0-9\s]/", "", $filename);
    $filename = str_replace(" ", "-", $filename);
    $filename = str_replace(".", "", $filename);
    return $filename;
}

function validateFileExtension($fileExtension)
{
    $allowedExtensions = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
    return in_array($fileExtension, $allowedExtensions);
}

function getLogoFromUrl($url, $uploadDir, $name, $settings)
{
    $maxRedirects = 3;
    $currentUrl = $url;

    for ($i = 0; $i <= $maxRedirects; $i++) {
        if (!filter_var($currentUrl, FILTER_VALIDATE_URL) || !preg_match('/^https?:\/\//i', $currentUrl)) {
            return ['success' => false, 'message' => 'Invalid URL format.'];
        }

        $parts = parse_url($currentUrl);
        $host = $parts['host'];
        $port = $parts['port'] ?? ($parts['scheme'] === 'https' ? 443 : 80);
        $ip = gethostbyname($host);

        if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE) === false 
            || is_cgnat_ip($ip)) {
            return ['success' => false, 'message' => 'Invalid IP Address.'];
        }

        $ch = curl_init($currentUrl);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
        curl_setopt($ch, CURLOPT_TIMEOUT, 5);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);
        curl_setopt($ch, CURLOPT_RESOLVE, ["$host:$port:$ip"]);

        $imageData = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);

        if ($httpCode >= 300 && $httpCode < 400) {
            $redirectUrl = curl_getinfo($ch, CURLINFO_REDIRECT_URL);
            unset($ch);
            if (!$redirectUrl) {
                break;
            }
            $currentUrl = $redirectUrl;
            continue; 
        }

        if ($imageData !== false && $httpCode === 200) {
            $timestamp = time();
            $fileName = $timestamp . '-' . sanitizeFilename($name) . '.png';
            $uploadFile = $uploadDir . $fileName;

            if (saveLogo($imageData, $uploadFile, $name, $settings)) {
                unset($ch);
                return ['success' => true, 'filename' => $fileName];
            }

            unset($ch);
            return ['success' => false, 'message' => 'Failed to save logo image.'];
        }

        unset($ch);
        break;
    }

    return ['success' => false, 'message' => 'Failed to fetch image.'];
}

function saveLogo($imageData, $uploadFile, $name, $settings)
{
    $image = imagecreatefromstring($imageData);
    $removeBackground = isset($settings['removeBackground']) && $settings['removeBackground'] === 'true';

    if ($image !== false) {
        $tempFile = tempnam(sys_get_temp_dir(), 'logo');
        imagealphablending($image, false);
        imagesavealpha($image, true);
        imagepng($image, $tempFile);
        imagedestroy($image);

        $newImage = imagecreatefrompng($tempFile);
        if ($newImage !== false) {
            imagealphablending($newImage, false);
            imagesavealpha($newImage, true);

            if ($removeBackground) {
                require_once __DIR__ . '/../../includes/gd_background_removal.php';
                if (!imageistruecolor($newImage)) {
                    imagepalettetotruecolor($newImage);
                    imagealphablending($newImage, false);
                    imagesavealpha($newImage, true);
                }
                $corner = imagecolorat($newImage, 0, 0);
                if ((($corner >> 24) & 0x7F) !== 127) {
                    gdRemoveBackgroundColor($newImage, ($corner >> 16) & 0xFF, ($corner >> 8) & 0xFF, $corner & 0xFF);
                }
            }

            require_once __DIR__ . '/../../includes/gd_background_removal.php';
            $newImage = gdCropTransparent($newImage, 2);
            $saved = imagepng($newImage, $uploadFile);
            imagedestroy($newImage);
        } else {
            unlink($tempFile);
            return false;
        }

        unlink($tempFile);
        return $saved;
    }
    return false;
}

function resizeAndUploadLogo($uploadedFile, $uploadDir, $name, $settings)
{
    $targetWidth = 135;
    $targetHeight = 42;

    $timestamp = time();
    $originalFileName = $uploadedFile['name'];
    $fileExtension = pathinfo($originalFileName, PATHINFO_EXTENSION);
    $fileExtension = validateFileExtension($fileExtension) ? $fileExtension : 'png';
    $fileName = $timestamp . '-' . sanitizeFilename($name) . '.' . $fileExtension;
    $uploadFile = $uploadDir . $fileName;

    if (move_uploaded_file($uploadedFile['tmp_name'], $uploadFile)) {
        $fileInfo = getimagesize($uploadFile);

        if ($fileInfo !== false) {
            $width = $fileInfo[0];
            $height = $fileInfo[1];

            if ($fileExtension === 'png') {
                $image = imagecreatefrompng($uploadFile);
            } elseif ($fileExtension === 'jpg' || $fileExtension === 'jpeg') {
                $image = imagecreatefromjpeg($uploadFile);
            } elseif ($fileExtension === 'gif') {
                $image = imagecreatefromgif($uploadFile);
            } elseif ($fileExtension === 'webp') {
                $image = imagecreatefromwebp($uploadFile);
            } else {
                return "";
            }

            if ($fileExtension === 'png') {
                imagesavealpha($image, true);
            }

            require_once __DIR__ . '/../../includes/gd_background_removal.php';
            $image = gdCropTransparent($image, 2);
            $width = imagesx($image);
            $height = imagesy($image);

            $newWidth = $width;
            $newHeight = $height;

            if ($width > $targetWidth) {
                $newWidth = (int) $targetWidth;
                $newHeight = (int) (($targetWidth / $width) * $height);
            }

            if ($newHeight > $targetHeight) {
                $newWidth = (int) (($targetHeight / $newHeight) * $newWidth);
                $newHeight = (int) $targetHeight;
            }

            $resizedImage = imagecreatetruecolor($newWidth, $newHeight);
            imagesavealpha($resizedImage, true);
            $transparency = imagecolorallocatealpha($resizedImage, 0, 0, 0, 127);
            imagefill($resizedImage, 0, 0, $transparency);
            imagecopyresampled($resizedImage, $image, 0, 0, 0, 0, $newWidth, $newHeight, $width, $height);

            if ($fileExtension === 'png') {
                $saved = imagepng($resizedImage, $uploadFile);
            } elseif ($fileExtension === 'jpg' || $fileExtension === 'jpeg') {
                $saved = imagejpeg($resizedImage, $uploadFile);
            } elseif ($fileExtension === 'gif') {
                $saved = imagegif($resizedImage, $uploadFile);
            } elseif ($fileExtension === 'webp') {
                $saved = imagewebp($resizedImage, $uploadFile);
            } else {
                return "";
            }

            imagedestroy($image);
            imagedestroy($resizedImage);

            if (!$saved) {
                if (file_exists($uploadFile)) {
                    unlink($uploadFile);
                }
                return "";
            }

            return $fileName;
        }
    }
    return "";
}

// Themed variant generation piggybacks on the same "remove background"
// setting: both only make sense for logos we're already reprocessing, and
// this avoids running pixel classification on every single upload.
function generateLogoThemeVariant($logo, $removeBackgroundEnabled)
{
    $logoTextColor = null;
    $logoVariant = null;

    if ($logo !== "" && $removeBackgroundEnabled) {
        $logoExtension = strtolower(pathinfo($logo, PATHINFO_EXTENSION));
        $logoPath = '../../images/uploads/logos/' . $logo;

        if ($logoExtension === 'png' || $logoExtension === 'webp') {
            $sourceImage = $logoExtension === 'png' ? imagecreatefrompng($logoPath) : imagecreatefromwebp($logoPath);

            if ($sourceImage !== false) {
                imagealphablending($sourceImage, false);
                imagesavealpha($sourceImage, true);

                $logoTextColor = classifyLogoTextColor($sourceImage);

                if ($logoTextColor !== null) {
                    $variantImage = generateThemedLogoVariant($sourceImage);
                    $logoVariant = pathinfo($logo, PATHINFO_FILENAME) . '-variant.png';
                    imagepng($variantImage, '../../images/uploads/logos/' . $logoVariant);
                    imagedestroy($variantImage);
                }

                imagedestroy($sourceImage);
            }
        }
    }

    return [$logoTextColor, $logoVariant];
}

require_once '../../includes/shelflife/subscription_service.php';

/**
 * ShelfLife: the API fields a request may set, keyed by column. Only the keys
 * actually posted are passed on, so an edit changes just what was sent.
 */
function shelflife_api_input()
{
    $input = [];
    foreach ([
        'name', 'price', 'currency_id', 'frequency', 'cycle', 'next_payment', 'start_date', 'auto_renew',
        'payment_method_id', 'payer_user_id', 'category_id', 'notes', 'url', 'notify_days_before',
        'inactive', 'cancellation_date', 'replacement_subscription_id', 'kind',
    ] as $field) {
        if (isset($_POST[$field])) {
            $input[$field] = $_POST[$field];
        }
    }
    if (isset($_POST['notify']) || isset($_POST['notifications'])) {
        $input['notify'] = $_POST['notify'] ?? $_POST['notifications'];
    }

    return $input;
}

function shelflife_api_reject(ShelfLifeValidationError $e)
{
    echo json_encode([
        'success' => false,
        'title' => 'Invalid parameter',
        'message' => $e->getMessage()
    ]);
    exit;
}

switch ($action) {
    case 'add':
        $input = shelflife_api_input();
        if (!isset($input['start_date'])) {
            $input['start_date'] = date('Y-m-d');
        }

        // Validate required fields. A price and a frequency are only needed for
        // what is paid for and what repeats.
        $kind = $input['kind'] ?? SHELFLIFE_KIND_SUBSCRIPTION;
        $needsPrice = $kind === SHELFLIFE_KIND_SUBSCRIPTION;
        $needsFrequency = (string) ($input['cycle'] ?? '') !== (string) SHELFLIFE_CYCLE_ONE_TIME;
        if (empty($input['name']) || trim($input['name']) === '' || ($needsPrice && !isset($input['price'])) || empty($input['currency_id'])
            || ($needsFrequency && empty($input['frequency'])) || empty($input['cycle']) || empty($input['next_payment'])) {
            echo json_encode([
                'success' => false,
                'title' => 'Missing parameters',
                'message' => 'Parameters "name", "price", "currency_id", "frequency", "cycle", and "next_payment" are required.'
            ]);
            exit;
        }

        try {
            $subscriptionData = shelflife_subscription_prepare($db, $userId, $input);
        } catch (ShelfLifeValidationError $e) {
            shelflife_api_reject($e);
        }
        $name = $subscriptionData['name'];

        // Process Logo
        $logo = '';
        $logoWarning = '';
        $logoUrl = $_POST['logo_url'] ?? $_POST['logo-url'] ?? '';
        if ($logoUrl !== "") {
            $resLogo = getLogoFromUrl($logoUrl, '../../images/uploads/logos/', $name, $settings);
            if ($resLogo['success']) {
                $logo = $resLogo['filename'];
            } else {
                $logoWarning = $resLogo['message'];
            }
        } elseif (!empty($_FILES['logo']['name'])) {
            $fileType = mime_content_type($_FILES['logo']['tmp_name']);
            if (strpos($fileType, 'image') !== false) {
                $logo = resizeAndUploadLogo($_FILES['logo'], '../../images/uploads/logos/', $name, $settings);
                if ($logo === "") {
                    $logoWarning = 'Failed to save logo image.';
                }
            }
        }

        [$logoTextColor, $logoVariant] = generateLogoThemeVariant($logo, $removeBackgroundEnabled);

        // Insert
        try {
            $newSubscriptionId = shelflife_subscription_insert($db, $userId, $subscriptionData, [
                'logo' => $logo,
                'logo_text_color' => $logoTextColor,
                'logo_variant' => $logoVariant,
            ]);
            $inserted = true;
        } catch (RuntimeException $e) {
            $inserted = false;
            $insertError = $e->getMessage();
        }

        if ($inserted) {
            $addResponse = [
                'success' => true,
                'title' => 'Subscription added',
                'subscriptionId' => $newSubscriptionId,
                'message' => 'Subscription added successfully.'
            ];
            if ($logoWarning !== '') {
                $addResponse['logo_warning'] = $logoWarning;
            }
            echo json_encode($addResponse);
        } else {
            echo json_encode([
                'success' => false,
                'title' => 'Database error',
                'message' => $insertError
            ]);
        }
        break;

    case 'edit':
        $subscriptionId = $_POST['subscriptionId'] ?? $_POST['id'] ?? $_POST['subscription_id'] ?? null;
        if (!$subscriptionId) {
            echo json_encode([
                'success' => false,
                'title' => 'Missing parameter',
                'message' => 'Parameter "id" (or "subscriptionId") is required.'
            ]);
            exit;
        }
        $subscriptionId = intval($subscriptionId);

        // Fetch current subscription
        $subSql = "SELECT * FROM subscriptions WHERE id = :subId AND user_id = :userId";
        $subStmt = $db->prepare($subSql);
        $subStmt->bindValue(':subId', $subscriptionId, SQLITE3_INTEGER);
        $subStmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
        $subResult = $subStmt->execute();
        $subscription = $subResult->fetchArray(SQLITE3_ASSOC);

        if (!$subscription) {
            echo json_encode([
                'success' => false,
                'title' => 'Subscription not found',
                'message' => 'Subscription not found or does not belong to you.'
            ]);
            exit;
        }

        // Only the posted fields change; the rest keeps the stored values.
        try {
            $subscriptionData = shelflife_subscription_prepare($db, $userId, shelflife_api_input(), $subscription);
        } catch (ShelfLifeValidationError $e) {
            shelflife_api_reject($e);
        }
        $name = $subscriptionData['name'];

        // Process Logo
        $logo = $subscription['logo'];
        $logoTextColor = $subscription['logo_text_color'];
        $logoVariant = $subscription['logo_variant'];
        $logoChanged = false;
        $logoWarning = '';
        $logoUrl = $_POST['logo_url'] ?? $_POST['logo-url'] ?? '';
        if ($logoUrl !== "") {
            $resLogo = getLogoFromUrl($logoUrl, '../../images/uploads/logos/', $name, $settings);
            if ($resLogo['success']) {
                $logo = $resLogo['filename'];
                $logoChanged = true;
            } else {
                $logoWarning = $resLogo['message'];
            }
        } elseif (!empty($_FILES['logo']['name'])) {
            $fileType = mime_content_type($_FILES['logo']['tmp_name']);
            if (strpos($fileType, 'image') !== false) {
                $newLogo = resizeAndUploadLogo($_FILES['logo'], '../../images/uploads/logos/', $name, $settings);
                if ($newLogo !== "") {
                    $logo = $newLogo;
                    $logoChanged = true;
                } else {
                    $logoWarning = 'Failed to save logo image.';
                }
            }
        }

        if ($logoChanged) {
            [$logoTextColor, $logoVariant] = generateLogoThemeVariant($logo, $removeBackgroundEnabled);
        }

        // Update
        try {
            shelflife_subscription_update($db, $userId, $subscriptionId, $subscriptionData, [
                'logo' => $logo,
                'logo_text_color' => $logoTextColor,
                'logo_variant' => $logoVariant,
            ]);
            $updated = true;
        } catch (RuntimeException $e) {
            $updated = false;
            $updateError = $e->getMessage();
        }

        if ($updated) {
            $updateResponse = [
                'success' => true,
                'title' => 'Subscription updated',
                'message' => 'Subscription updated successfully.'
            ];
            if ($logoWarning !== '') {
                $updateResponse['logo_warning'] = $logoWarning;
            }
            echo json_encode($updateResponse);
        } else {
            echo json_encode([
                'success' => false,
                'title' => 'Database error',
                'message' => $updateError
            ]);
        }
        break;

    case 'delete':
        $subscriptionId = $_POST['subscriptionId'] ?? $_POST['id'] ?? $_POST['subscription_id'] ?? null;
        if (!$subscriptionId) {
            echo json_encode([
                'success' => false,
                'title' => 'Missing parameter',
                'message' => 'Parameter "id" (or "subscriptionId") is required.'
            ]);
            exit;
        }
        $subscriptionId = intval($subscriptionId);

        // Check ownership
        $checkSql = "SELECT * FROM subscriptions WHERE id = :subId AND user_id = :userId";
        $checkStmt = $db->prepare($checkSql);
        $checkStmt->bindValue(':subId', $subscriptionId, SQLITE3_INTEGER);
        $checkStmt->bindValue(':userId', $userId, SQLITE3_INTEGER);
        $checkResult = $checkStmt->execute();
        $subscription = $checkResult->fetchArray(SQLITE3_ASSOC);

        if (!$subscription) {
            echo json_encode([
                'success' => false,
                'title' => 'Subscription not found',
                'message' => 'Subscription not found or does not belong to you.'
            ]);
            exit;
        }

        // Delete
        $sqlDelete = "DELETE FROM subscriptions WHERE id = :subId AND user_id = :userId";
        $stmtDelete = $db->prepare($sqlDelete);
        $stmtDelete->bindParam(':subId', $subscriptionId, SQLITE3_INTEGER);
        $stmtDelete->bindParam(':userId', $userId, SQLITE3_INTEGER);

        if ($stmtDelete->execute()) {
            // Nullify replacement_subscription_id references pointing to this subscription
            $queryCascade = "UPDATE subscriptions SET replacement_subscription_id = NULL WHERE replacement_subscription_id = :subId AND user_id = :userId";
            $stmtCascade = $db->prepare($queryCascade);
            $stmtCascade->bindParam(':subId', $subscriptionId, SQLITE3_INTEGER);
            $stmtCascade->bindParam(':userId', $userId, SQLITE3_INTEGER);
            $stmtCascade->execute();

            echo json_encode([
                'success' => true,
                'title' => 'Subscription deleted',
                'message' => 'Subscription deleted successfully.'
            ]);
        } else {
            echo json_encode([
                'success' => false,
                'title' => 'Database error',
                'message' => 'Failed to delete subscription.'
            ]);
        }
        break;
}

$db->close();
?>
