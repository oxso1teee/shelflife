<?php
$version = "v5.8.3";
// ShelfLife: version of the static files for cache busting, see includes/shelflife/asset_version.php
require_once __DIR__ . '/shelflife/asset_version.php';
$assetVersion = shelflife_asset_version($version);
?>
