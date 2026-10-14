<?php
/*
  ShelfLife: the version static files are requested and cached under
  (includes/shelflife/asset_version.php). It must change with any stylesheet,
  script or image, and stay the same otherwise.
*/

require_once WALLOS_ROOT . '/includes/shelflife/asset_version.php';

/**
 * A throwaway web root with a stylesheet, a script, an icon and an uploaded logo.
 *
 * @return string
 */
function shelflife_asset_fixture()
{
    $root = sys_get_temp_dir() . '/shelflife-assets-' . bin2hex(random_bytes(6));
    foreach (['styles', 'scripts', 'images/icon', 'images/uploads/logos'] as $dir) {
        mkdir($root . '/' . $dir, 0777, true);
    }
    file_put_contents($root . '/styles/styles.css', 'body { color: #000; }');
    file_put_contents($root . '/scripts/common.js', 'console.log(1);');
    file_put_contents($root . '/images/icon/favicon.ico', 'icon');
    file_put_contents($root . '/images/uploads/logos/netflix.png', 'logo');

    return $root;
}

function shelflife_asset_fixture_remove($root)
{
    $files = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST
    );
    foreach ($files as $file) {
        $file->isDir() ? rmdir($file->getPathname()) : unlink($file->getPathname());
    }
    rmdir($root);
}

wallos_test('the asset revision is stable while the files stay the same', function () {
    $root = shelflife_asset_fixture();
    try {
        $revision = shelflife_asset_revision_compute($root);
        assert_true(preg_match('/^[0-9a-f]{12}$/', $revision) === 1, '12 hex characters');
        touch($root . '/styles/styles.css', time() + 60);
        assert_same($revision, shelflife_asset_revision_compute($root), 'a new modification time alone changes nothing');
    } finally {
        shelflife_asset_fixture_remove($root);
    }
});

wallos_test('the asset revision changes with a stylesheet, a script, an icon or a new file', function () {
    $root = shelflife_asset_fixture();
    try {
        $changes = [
            'stylesheet' => fn() => file_put_contents($root . '/styles/styles.css', 'body { color: #111; }'),
            'script' => fn() => file_put_contents($root . '/scripts/common.js', 'console.log(2);'),
            'icon' => fn() => file_put_contents($root . '/images/icon/favicon.ico', 'new icon'),
            'new file' => fn() => file_put_contents($root . '/scripts/telegram_link.js', ''),
        ];
        foreach ($changes as $what => $change) {
            $before = shelflife_asset_revision_compute($root);
            $change();
            assert_true($before !== shelflife_asset_revision_compute($root), 'a changed ' . $what . ' gives a new revision');
        }
    } finally {
        shelflife_asset_fixture_remove($root);
    }
});

wallos_test('uploaded logos are not part of the asset revision', function () {
    $root = shelflife_asset_fixture();
    try {
        $before = shelflife_asset_revision_compute($root);
        file_put_contents($root . '/images/uploads/logos/spotify.png', 'another upload');
        assert_same($before, shelflife_asset_revision_compute($root), 'user uploads do not invalidate every cached file');
    } finally {
        shelflife_asset_fixture_remove($root);
    }
});

wallos_test('the asset version is the Wallos version plus the revision', function () {
    assert_true(preg_match('/^v5\.8\.3-[0-9a-f]{12}$/', shelflife_asset_version('v5.8.3')) === 1, 'e.g. v5.8.3-1a2b3c4d5e6f');
});

wallos_test('pages request stylesheets and scripts under the asset version', function () {
    $offenders = [];
    $pages = array_merge(glob(WALLOS_ROOT . '/*.php'), glob(WALLOS_ROOT . '/includes/*.php'));
    foreach ($pages as $page) {
        if (strpos(file_get_contents($page), '?<?= $version ?>') !== false) {
            $offenders[] = basename($page);
        }
    }
    assert_same([], $offenders, 'no page still uses the Wallos version alone as the cache-buster');
    assert_contains('?<?= $assetVersion ?>', file_get_contents(WALLOS_ROOT . '/includes/header.php'),
        'the header requests its files under the asset version');
});

wallos_test('the service worker takes a newer page\'s files from the network', function () {
    $source = file_get_contents(WALLOS_ROOT . '/service-worker.php');
    $staticBranch = substr($source, strpos($source, 'Static assets: cache-first'));
    $staticBranch = substr($staticBranch, 0, strpos($staticBranch, 'PHP pages and everything else'));

    assert_contains("url.search !== '?' + ASSET_VERSION", $staticBranch,
        'a request for another version is not answered from this worker\'s older cache');
    assert_contains('fetch(request).catch(() => caches.match(request, { ignoreSearch: true }))', $staticBranch,
        'offline, the cached copy is still served');
});
