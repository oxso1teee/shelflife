<?php
/*
  ShelfLife: one version for all static files (CSS, JS, fonts, images).

  Wallos versions both the service worker's static cache and the "?v5.8.3"
  query string of every stylesheet and script by $version alone, so a change
  to a stylesheet, a script or an icon made without a new Wallos release never
  reached a browser that had the site cached. $assetVersion is $version plus a
  hash of the files' contents, so it changes whenever any of them does.

  - The Docker build writes the hash once to asset_revision.php (see the
    Dockerfile); without that file (development, tests) it is computed here.
  - Uploaded logos (images/uploads/logos) are user data, not part of it.
*/

const SHELFLIFE_ASSET_DIRS = ['styles', 'scripts', 'webfonts', 'images', 'tma'];

/**
 * Hash of the static files under $root: their paths and contents.
 *
 * @param string $root the web root
 * @return string 12 hex characters
 */
function shelflife_asset_revision_compute($root)
{
    $files = [];
    foreach (SHELFLIFE_ASSET_DIRS as $dir) {
        if (!is_dir($root . '/' . $dir)) {
            continue;
        }
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($root . '/' . $dir, FilesystemIterator::SKIP_DOTS)
        );
        foreach ($iterator as $file) {
            $relative = substr($file->getPathname(), strlen($root) + 1);
            if ($file->isFile() && strpos($relative, 'images/uploads/logos/') !== 0) {
                $files[] = $relative;
            }
        }
    }
    sort($files, SORT_STRING);

    $hash = hash_init('sha256');
    foreach ($files as $relative) {
        hash_update($hash, $relative . "\0");
        hash_update_file($hash, $root . '/' . $relative);
    }

    return substr(hash_final($hash), 0, 12);
}

/**
 * The version static files are requested and cached under, e.g. "v5.8.3-1a2b3c4d5e6f".
 *
 * @param string $baseVersion the Wallos version ($version)
 * @return string
 */
function shelflife_asset_version($baseVersion)
{
    static $revision = null;
    if ($revision === null) {
        $built = __DIR__ . '/asset_revision.php';
        $revision = is_file($built) ? (string) include $built : shelflife_asset_revision_compute(dirname(__DIR__, 2));
    }

    return $baseVersion . '-' . $revision;
}
