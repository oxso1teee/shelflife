<?php
require_once '../../includes/connect_endpoint.php';
require_once '../../includes/validate_endpoint.php';
require_once '../../includes/shelflife/subscription_service.php';

$postData = file_get_contents("php://input");
$data = json_decode($postData, true);

$subscriptionId = (int) ($data["id"] ?? 0);

// The dashboard offers manual renewal only for recurring records that do not
// renew automatically; the bot's "renewed" button uses the same service below.
$subscriptionToRenew = shelflife_subscription_find($db, $userId, $subscriptionId);
if ($subscriptionToRenew === null || (int) $subscriptionToRenew['auto_renew'] !== 0 || (int) $subscriptionToRenew['cycle'] === SHELFLIFE_CYCLE_ONE_TIME) {
    die(json_encode([
        "success" => false,
        "message" => translate("error", $i18n)
    ]));
}

$result = shelflife_subscription_renew($db, $userId, $subscriptionId, shelflife_today(), $subscriptionToRenew['next_payment']);

if ($result['status'] === 'renewed') {
    $response = [
        "success" => true,
        "message" => translate('success', $i18n),
        "id" => $subscriptionId
    ];
    echo json_encode($response);
} else {
    die(json_encode([
        "success" => false,
        "message" => translate("error", $i18n)
    ]));
}
