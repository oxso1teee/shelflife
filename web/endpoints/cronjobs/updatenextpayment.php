<?php

require_once 'validate.php';
require_once __DIR__ . '/../../includes/connect_endpoint_crontabs.php';

require 'settimezone.php';

$date = new DateTime('now');
echo "\n" . $date->format('Y-m-d') . " " . $date->format('H:i:s') . "<br />\n";
echo $timezone . "<br />\n";

$currentDate = new DateTime();
$currentDateString = $currentDate->format('Y-m-d');

// ShelfLife: the period arithmetic lives in includes/shelflife, shared with the
// renew endpoint and the bot. It keeps a payment due on the 31st on the last
// day of shorter months and does not skip a due date that falls on today.
require_once __DIR__ . '/../../includes/shelflife/subscription_service.php';

$moved = shelflife_advance_overdue_auto_renewals($db, $currentDateString);
echo "Moved $moved overdue auto-renewing records<br />\n";

$formattedDate = $currentDate->format('Y-m-d');

$deleteQuery = "DELETE FROM last_update_next_payment_date";
$deleteStmt = $db->prepare($deleteQuery);
$deleteResult = $deleteStmt->execute();

$query = "INSERT INTO last_update_next_payment_date (date) VALUES (:formattedDate)";
$stmt = $db->prepare($query);
$stmt->bindParam(':formattedDate', $currentDateString, SQLITE3_TEXT);
$result = $stmt->execute();

echo "Updated next payment dates";
?>