# ios-accessibility-capture

Captures the iOS accessibility tree of the open-source Wikipedia iOS app on a GitHub-hosted
macOS runner, using `idb ui describe-all`, and uploads it as a build artifact.

Purpose: obtain a real iOS accessibility surface without Apple hardware, so that a
cross-platform UI-testing experiment can compare web, Android and iOS surfaces of one product.

Run from the Actions tab. Contains only the capture tooling.
