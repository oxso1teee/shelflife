<?php
error_reporting(E_ERROR | E_PARSE);
require_once '../../includes/connect_endpoint.php';
require_once '../../includes/validate_endpoint.php';
require_once '../../includes/inputvalidation.php';
require_once '../../includes/getsettings.php';
require_once '../../includes/ssrf_helper.php';
require_once '../../includes/logo_theme_variant.php';
require_once '../../includes/logo_cleanup.php';

if (!file_exists('../../images/uploads/logos')) {
    mkdir('../../images/uploads/logos', 0777, true);
    mkdir('../../images/uploads/logos/avatars', 0777, true);
}

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

function getLogoFromUrl($url, $uploadDir, $name, $settings, $i18n)
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
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false); // Manual handling to re-validate IPs
        
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
            $uploadFile = $uploadDir . $fileName; // Note: Use the provided $uploadDir variable

            if (saveLogo($imageData, $uploadFile, $name, $settings)) {
                unset($ch);
                return ['success' => true, 'filename' => $fileName];
            }

            unset($ch);
            return ['success' => false, 'message' => translate('error_saving_logo', $i18n)];
        }

        $error = curl_error($ch);
        unset($ch);
        return ['success' => false, 'message' => translate('error_fetching_image', $i18n) . ': ' . $error];
    }

    return ['success' => false, 'message' => translate('error_fetching_image', $i18n)];
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
                // On palette images imagecolorat() returns palette indexes, not RGB values
                if (!imageistruecolor($newImage)) {
                    imagepalettetotruecolor($newImage);
                    imagealphablending($newImage, false);
                    imagesavealpha($newImage, true);
                }
                // Paint out the corner color with ~10% fuzz
                $corner = imagecolorat($newImage, 0, 0);
                if ((($corner >> 24) & 0x7F) !== 127) {
                    gdRemoveBackgroundColor($newImage, ($corner >> 16) & 0xFF, ($corner >> 8) & 0xFF, $corner & 0xFF);
                }
            }

            // Crop/trim transparent margins
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

            // Crop/trim transparent margins (ensure we update dimensions after cropping)
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

require_once '../../includes/shelflife/subscription_service.php';

// Answers the form with an error the page shows to the user.
function rejectForeignId($message)
{
    header('Content-Type: application/json');
    echo json_encode(['status' => 'Error', 'message' => $message]);
    exit();
}

$isEdit = isset($_POST['id']) && $_POST['id'] != "";
$id = $isEdit ? (int) $_POST['id'] : null;
$existing = null;
if ($isEdit) {
    $existing = shelflife_subscription_find($db, $userId, $id);
    if ($existing === null) {
        rejectForeignId('The subscription does not exist or does not belong to you.');
    }
}

// ShelfLife: validation, the ownership checks on every referenced id and the
// write itself are shared with the API, the bot and the cron jobs
// (includes/shelflife/subscription_service.php). The form posts every field,
// so unticked checkboxes are passed as false rather than left out.
$input = [
    'name' => $_POST['name'] ?? '',
    'price' => $_POST['price'] ?? null,
    'currency_id' => $_POST['currency_id'] ?? null,
    'frequency' => $_POST['frequency'] ?? null,
    'cycle' => $_POST['cycle'] ?? null,
    'next_payment' => $_POST['next_payment'] ?? null,
    'auto_renew' => isset($_POST['auto_renew']),
    'start_date' => $_POST['start_date'] ?? null,
    'payment_method_id' => $_POST['payment_method_id'] ?? null,
    'payer_user_id' => $_POST['payer_user_id'] ?? null,
    'category_id' => $_POST['category_id'] ?? null,
    'notes' => $_POST['notes'] ?? '',
    'url' => $_POST['url'] ?? '',
    'notify' => isset($_POST['notifications']),
    'notify_days_before' => $_POST['notify_days_before'] ?? null,
    'inactive' => isset($_POST['inactive']),
    'cancellation_date' => $_POST['cancellation_date'] ?? null,
    'replacement_subscription_id' => $_POST['replacement_subscription_id'] ?? null,
];
if (isset($_POST['kind'])) {
    $input['kind'] = $_POST['kind'];
}

try {
    $subscriptionData = shelflife_subscription_prepare($db, $userId, $input, $existing);
} catch (ShelfLifeValidationError $e) {
    rejectForeignId($e->getMessage());
}

$name = $subscriptionData['name'];
$logoUrl = validate($_POST['logo-url'] ?? '');
$logo = "";
$logoError = "";

if ($logoUrl !== "") {
    $result = getLogoFromUrl($logoUrl, '../../images/uploads/logos/', $name, $settings, $i18n);
    if ($result['success']) {
        $logo = $result['filename'];
    } else {
        $logoError = $result['message'];
    }
} else {
    if (!empty($_FILES['logo']['name'])) {
        $fileType = mime_content_type($_FILES['logo']['tmp_name']);
        if (strpos($fileType, 'image') === false) {
            echo translate("fill_all_fields", $i18n);
            exit();
        }
        $logo = resizeAndUploadLogo($_FILES['logo'], '../../images/uploads/logos/', $name, $settings);
        if ($logo === "") {
            $logoError = translate('error_saving_logo', $i18n);
        }
    }
}

$logoTextColor = null;
$logoVariant = null;
$removeBackgroundEnabled = isset($settings['removeBackground']) && $settings['removeBackground'] === 'true';

// Themed variant generation piggybacks on the same "remove background"
// setting: both only make sense for logos we're already reprocessing, and
// this avoids running pixel classification on every single upload.
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

$newLogo = $logo != "" ? ['logo' => $logo, 'logo_text_color' => $logoTextColor, 'logo_variant' => $logoVariant] : null;

// When the logo is being replaced, remember the old files so they can be
// removed after the update instead of lingering as orphans.
$oldLogo = $isEdit && $newLogo !== null ? $existing['logo'] : null;
$oldLogoVariant = $isEdit && $newLogo !== null ? $existing['logo_variant'] : null;

try {
    if (!$isEdit) {
        shelflife_subscription_insert($db, $userId, $subscriptionData, $newLogo ?? []);
    } else {
        shelflife_subscription_update($db, $userId, $id, $subscriptionData, $newLogo);
    }
    $saved = true;
} catch (RuntimeException $e) {
    error_log('ShelfLife: saving a subscription failed: ' . $e->getMessage());
    $saved = false;
}

if ($saved) {
    $success['status'] = "Success";
    $text = $isEdit ? "updated" : "added";
    $success['message'] = translate('subscription_' . $text . '_successfuly', $i18n);
    if ($logoError !== "") {
        $success['logo_warning'] = $logoError;
    }

    // The logo was just replaced: drop the previous files if nothing else uses them.
    if ($isEdit && $logo != "") {
        if ($oldLogo !== null && $oldLogo !== $logo) {
            deleteLogoFileIfUnused($db, $oldLogo, '../../images/uploads/logos/');
        }
        if ($oldLogoVariant !== null && $oldLogoVariant !== $logoVariant) {
            deleteLogoFileIfUnused($db, $oldLogoVariant, '../../images/uploads/logos/');
        }
    }

    header('Content-Type: application/json');
    echo json_encode($success);
    exit();
} else {
    rejectForeignId(translate('error', $i18n));
}
$db->close();
?>