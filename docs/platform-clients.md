# Platform Clients

## Fire OS

`apps/fire-tv` is an Expo SDK 57 application that uses the `react-native-tvos` 0.86 fork and the official TV config plugin. It is a separate presentation surface because TV focus, remote input, landscape layout and the Android Leanback manifest are not phone concerns. The package participates in the root npm workspace; the mobile app uses the same React Native TV fork because Expo requires one React Native implementation across a monorepo.

The Android directory is generated locally with `npm run prebuild:fire-tv` and remains ignored. Produce and test an APK with Android Studio and an Android TV emulator or connected Fire TV. A successful JavaScript bundle or Android TV emulator run does not prove Fire OS device compatibility.

## Vega OS

`apps/vega` is the versioned Vega application created from Amazon's SDK 0.24 `helloWorld` template for React Native 0.83. Its package ID is `com.riippex.kinetiqv.vega`, and both its minimum and target operating-system versions are Vega OS 1.2. The current presentation is an unprivileged TV shell: it declares only the OS module required by the SDK and does not request device privileges.

Vega supplies its own React Native runtime and compatible platform modules. The application therefore remains outside the root npm workspaces and owns a separate `package-lock.json`. Run root workspace installation from the repository root and Vega installation commands only from `apps/vega`. Do not link it into the Expo workspace or independently upgrade React, React Native, or `@amazon-devices/*` packages. Use `vega project install --fix` only as a deliberate SDK compatibility update and review the resulting package changes.

### Ubuntu setup

Use a native x86_64 Ubuntu 20.04, 22.04, or 24.04 host with at least 20 GB free, KVM access, native `curl`, Node.js 18 or later, Watchman, `lz4`, and the Python 3.8 development libraries required for symbolication. Kinetiq development currently uses Node.js 24.19 and npm 11.17. Install Vega Developer Tools from Amazon's [SDK installation guide](https://developer.amazon.com/docs/vega/0.24/install-vega-sdk), select an SDK 0.24 release, and load the environment printed by the installer. Never save Amazon credentials, device codes, certificates, or SDK-local state in the repository.

The application is already versioned; `tools/bootstrap-vega.sh` never regenerates it or copies over source. From a shell where `vega`, `node`, and `npm` are available, run:

```bash
bash tools/bootstrap-vega.sh
```

The script performs a clean install from the Vega lockfile and runs `vega project doctor`. If `apps/vega` is missing, restore it from Git. Generate a fresh Amazon template only in a temporary directory when intentionally evaluating an SDK migration, then manually review the differences.

### Validation levels

SDK validation confirms source and package compatibility without claiming that the UI ran:

```bash
cd apps/vega
npm test -- --runInBand
npm run lint
vega project doctor
npm run build:app
vega exec vpt validate build/x86_64-release/kinetiq-v-vega_x86_64.vpkg
```

Emulator validation requires working KVM access. Start the Vega Virtual Device, install the matching x86_64 package, and manually verify launch, all D-pad routes, selection states, forward navigation, and Back behavior:

```bash
vega virtual-device start --timeout 120
vega run-app build/x86_64-release/kinetiq-v-vega_x86_64.vpkg com.riippex.kinetiqv.vega.main -d VirtualDevice
```

Real-device validation is a separate release requirement. Follow Amazon's [Developer Mode authentication](https://developer.amazon.com/docs/vega/0.24/developer-mode), check that the Fire TV runs OS 1.2, build the supported ARM package, install it, and repeat the remote, navigation, accessibility, network, resume, and performance checks on hardware. Amazon login, the on-screen device code, and vendor selection remain interactive user actions. Emulator success does not prove device compatibility, and SDK validation proves neither.
