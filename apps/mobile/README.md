# Kinetiq V Mobile

The phone client uses React Native, Expo development builds and Expo Router. It owns camera coordination, session setup and progress capture UX.

- Start Metro from the repository root with `npm run dev:mobile`.
- Launch the Android target with `npm run android`.
- Native permissions and camera packages are added with the first capture feature so the manifest follows executable behavior.
- Generate the local Android project with `npx expo prebuild --platform android`, then build an installable APK with `.\\android\\gradlew.bat assembleRelease`. Use JDK 17 and a short checkout path on Windows because native React Native builds can exceed legacy path limits. Set `EXPO_PUBLIC_KINETIQ_GRAPHQL_URL` to a phone-accessible HTTPS GraphQL endpoint before building a connected release.
