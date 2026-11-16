# Building Brain Mobile — developer preview

Native Expo / React Native Android and iOS client for the existing FastAPI FacilityGuard backend. Connects to an authorized HTTPS deployment using its current Basic Auth credentials, held in memory only. No public exposure or technician rollout: existing backend is single-admin and requires individual accounts, scoped permissions, rate limiting and security review.

## Run
Install Node.js 20.19+ and Android Studio or Expo Go compatible with SDK 54. From this directory:
```sh
npm install
npx expo install --fix
npm run typecheck
npx expo start
```
Open on an Android device with compatible Expo Go or use `npm run android` with configured Android tooling. iOS native builds require macOS/Xcode or a configured cloud build. No APK or store release is included.

Enter the HTTPS origin of a private, reachable Building Brain deployment and its authorized admin credentials. Do not use HTTP or disable certificate verification. Existing backend is not changed.

Implemented source: property selection, work order list/start/complete, equipment details, PM and inspection lists, document-grounded question/answer with citations, QR scanner. Labels must encode `buildingbrain:asset:123` with the real asset ID; label generation is not included. QR lookup is restricted to the selected property. No offline sync, push, photos, technician roles, document viewer, or PM completion yet.

Validation pending: install dependencies, typecheck, Android/iOS device tests, authentication and property scoping, work order status updates, QR permission/scan, error handling, AI citations. Do not use real customer records until reviewed.