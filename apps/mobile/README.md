# Workforce OS — mobile app (Android + iPhone)

One Expo / React Native codebase for both phones. Same features as the web app:
type **or speak** instructions (12 languages incl. Hindi, Marathi, Tamil, Telugu,
Bengali), watch tasks run, open results and share files, see what's waiting for your
approval, manage the workforce and memory, and use the emergency stop. Plus **push
notifications** when a task is done, needs your answer or needs approval.

## Run it on your phone (development build)

Voice and push use native modules, so the app runs as a *development build*
(Expo Go is not enough).

```bash
cd apps/mobile
cp .env.example .env          # Supabase URL + publishable key + API URL reachable from the phone
npm install
npx eas-cli@latest login      # free Expo account
npx eas-cli@latest init       # creates the Expo project ID (needed for push)
npx eas-cli@latest build --profile development --platform android   # or ios
# install the build on your phone from the link EAS gives you, then:
npx expo start --dev-client
```

`EXPO_PUBLIC_API_URL` must be reachable from the phone: your deployed API
(`https://…`) or your computer's LAN IP (`http://192.168.x.x:8000`), never `localhost`.
Add the app's origin to the API's `CORS_ORIGINS` only for the web build.

## Sign-in setup (Supabase, once)

The app signs in with a **6-digit email code** (no links to tap on the phone).
In Supabase → Authentication → Email Templates → *Magic Link*, include the code:

```
<p>Your Workforce OS code is <strong>{{ .Token }}</strong></p>
```

## Push notifications

- Android: add FCM V1 credentials to the Expo project (`eas credentials`).
- iPhone: needs an Apple Developer account; EAS sets up the push key.
- The worker sends pushes through Expo's push service. Optional: set
  `EXPO_ACCESS_TOKEN` on the worker if you enable enhanced push security.

## Publish to Play Store / App Store

```bash
npx eas-cli@latest build --profile production --platform all
npx eas-cli@latest submit --platform android   # Google Play Console account
npx eas-cli@latest submit --platform ios       # Apple Developer account
```

Before the first release change `com.workforceos.app` in `app.json` to your own
bundle ID, and fill in store listings, privacy details (microphone + speech are used
only to turn your voice into an instruction) and screenshots. Store review is
decided by Google and Apple.

## Checks

```bash
npm run typecheck && npx expo lint && npx expo-doctor
npx expo export --platform android --platform ios   # bundles compile
```
