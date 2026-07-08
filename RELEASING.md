# Shipping updates

## Web / JS / backend changes  → nothing to do but push
The Android app loads the **live** server (`server.url` in `mobile/capacitor.config.json`
points at `…/ui/`). So any change to `backend/web/*` or the API deploys to every
phone the moment Railway finishes building. No APK, no store, no prompt.

Just: bump `version` in `backend/app/main.py` (`/health`) + the `CACHE` string in
`backend/web/sw.js`, commit, push. Done.

## Native changes → new APK + version bump
Only needed when you touch **native** bits: a new Capacitor plugin, an
`AndroidManifest.xml` permission, or Java under `mobile/android/app/src/main/java/…`.

1. **Bump the native version** in `mobile/android/app/build.gradle`:
   ```
   versionCode 2        // ← +1 every native release (this drives the update prompt)
   versionName "1.1"    // ← human label
   ```
2. **Build the release APK**:
   ```
   cd mobile
   npx cap sync android
   cd android
   ./gradlew.bat assembleRelease        # (or assembleDebug for a quick share build)
   ```
   Output: `mobile/android/app/build/outputs/apk/**/app-*.apk`
3. **Publish it** as a GitHub Release with the asset named **exactly `AARTH.apk`**
   (the landing page + in-app updater both point at `releases/latest/download/AARTH.apk`):
   ```
   cp <the-built>.apk /tmp/AARTH.apk
   gh release create v1.1 /tmp/AARTH.apk --title "AARTH v1.1" --notes "what changed"
   ```
4. **Tell the apps to update** — edit `backend/web/version.json`:
   ```json
   { "latestVersionCode": 2, "latestVersionName": "1.1",
     "apkUrl": "https://github.com/meetmaheshin/assime/releases/latest/download/AARTH.apk",
     "notes": "What's new in this build.", "mandatory": false }
   ```
   Set `mandatory: true` only for a breaking change (shows a blocking screen instead
   of a dismissable banner). Commit + push.

On next launch, any phone whose installed `versionCode` is below `latestVersionCode`
sees the "Update available" banner and taps to download the new APK. Phones already
on the latest code see nothing.
