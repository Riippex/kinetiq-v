# Kinetiq V Mobile

The phone client uses React Native, Expo development builds and Expo Router. It owns camera coordination, session setup and progress capture UX.

- Start Metro from the repository root with `npm run dev:mobile`.
- Launch the Android target with `npm run android`.
- Native permissions and camera packages are added with the first capture feature so the manifest follows executable behavior.
- Generate the local Android project with `npx expo prebuild --platform android`, then run `.\\gradlew.bat :app:assembleRelease` from `apps/mobile/android`. Use JDK 17 and a short, non-OneDrive checkout path on Windows because React Native Codegen requires regular local files and native builds can exceed legacy path limits. Set `EXPO_PUBLIC_KINETIQ_GRAPHQL_URL` to a phone-accessible HTTPS GraphQL endpoint before building a connected release.

## Authentication

Mobile uses the public Cognito app client with authorization code + PKCE. Cognito returns to `kinetiq://callback`; access and refresh tokens are stored with Expo SecureStore and never in AsyncStorage. Configure these public values in `apps/mobile/.env.local` before starting Metro or creating a native build:

```dotenv
EXPO_PUBLIC_KINETIQ_GRAPHQL_URL=https://example.com/graphql/
EXPO_PUBLIC_COGNITO_DOMAIN=example.auth.us-east-1.amazoncognito.com
EXPO_PUBLIC_COGNITO_MOBILE_CLIENT_ID=public-client-id
```

The access token is sent directly to Django as a bearer credential. The app refreshes it before expiry and revokes the current session during sign-out.

The native intent hook maps the exact `kinetiq://callback` and `kinetiq://logout`
returns to the home screen before routing. AuthSession independently receives
the original link and validates the authorization response through PKCE; the
router neither exchanges codes nor establishes a session. OAuth query parameters
are not propagated into router state. Other deep links remain unchanged.
See [Expo native intent routing](https://docs.expo.dev/router/advanced/native-intent/).
