# Platform Clients

## Fire OS

`apps/fire-tv` is an Expo SDK 57 application that uses the `react-native-tvos` 0.86 fork and the official TV config plugin. It is a separate presentation surface because TV focus, remote input, landscape layout and the Android Leanback manifest are not phone concerns. The package participates in the root npm workspace; the mobile app uses the same React Native TV fork because Expo requires one React Native implementation across a monorepo.

The Android directory is generated locally with `npm run prebuild:fire-tv` and remains ignored. Produce and test an APK with Android Studio and an Android TV emulator or connected Fire TV. A successful JavaScript bundle or Android TV emulator run does not prove Fire OS device compatibility.

## Vega OS

Vega SDK 0.24 supplies React Native 0.83 and platform modules from the operating system. It cannot share the root Expo runtime or npm lock safely, so the generated `apps/vega` project is intentionally excluded from root workspaces. On the Ubuntu development host, install Vega SDK 0.24 and run `bash tools/bootstrap-vega.sh`. The script generates Amazon's `helloWorld` template, applies package ID `com.riippex.kinetiqv.vega`, targets Vega OS 1.2, installs SDK-compatible packages, applies the Kinetiq TV shell and runs `vega project doctor`.

Run `npm run build:app` inside `apps/vega` to produce VPKG files. Validate with Vega Virtual Device first and a supported Fire TV device before submission. Do not add ordinary React or React Native runtime dependencies to the Vega application; they are system-provided.
