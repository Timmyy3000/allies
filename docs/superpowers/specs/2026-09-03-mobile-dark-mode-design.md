# Mobile dark mode design

## Status

Approved for implementation on 2026-09-03.

## Goal

Make the current Allies mobile experience follow the device light or dark mode.
Keep the visual rules in one small, reusable theme map.

## Scope

Apply the theme to the current mobile routes and shared UI:

- Welcome, onboarding, post-setup, Allies list, sign-in, and chat screens.
- Onboarding inputs, buttons, progress controls, and icons.
- Chat composer and account-creation modal.
- Status-bar icon color.

The existing `userInterfaceStyle: automatic` setting remains the source for
native device-mode support. An unspecified mode uses the light theme.

## Theme rules

The existing `Colors` and `useTheme` modules remain the theme boundary. Extend
them with semantic surface, text, control, and icon tokens. Screens must use
these tokens instead of adding local light/dark checks.

Dark mode uses:

| Token | Value | Use |
| --- | --- | --- |
| app background | `#000000` | Full-screen backgrounds |
| primary text | `#FFFFFF` | Main text and enabled button text |
| back button | `#161616` | Onboarding and chat back controls |
| onboarding input | `#161616` | Job and personality editors |
| chat input | `#121212` | Main chat composer |
| modal | `#161616` | Bottom-sheet surface |
| inactive button | `#202020` | Disabled and secondary buttons |
| modal cancel button | `#FFFFFF` | Modal close control |
| modal cancel icon | `#121212` | X icon on the cancel button |

Active buttons continue to use the selected Ally accent color. The default
accent is the Allies orange. Selecting another Ally color continues to update
active buttons and the Sign in link to that selected color.

Primary text becomes white. Existing supporting grey text remains grey unless
the current product rule explicitly requires white. The account modal's
“By continuing” privacy and terms text remains unchanged. Google and ChatGPT
sign-up labels use white text in dark mode.

Ally artwork, Ally colors, the orange Allies logo, provider logos, and the
privacy-policy treatment remain product colors rather than theme surfaces.

## Component behavior

- `PrimaryButton` keeps its animated accent behavior. Its disabled/secondary
  background and label colors come from the active theme.
- The shared bottom-sheet uses the modal surface token.
- Back, search, settings, and modal-close icons use the active theme color.
  The modal close control is white in dark mode with a `#121212` X.
- A single root status-bar configuration uses light icons in dark mode and dark
  icons in light mode. Screen-level fixed status-bar settings are removed.
- Device mode changes re-render through the existing React Native color-scheme
  hook. No manual theme toggle or new dependency is added.

## Non-goals

- No new theme provider, styling library, or design-token package.
- No change to Ally accent colors or artwork scale.
- No authentication, navigation, or persistence changes.
- No dynamic splash-screen redesign in this pass.

## Validation

Add a small theme contract test for the exact dark tokens. Run the targeted
mobile tests, `bun run lint:mobile`, and the mobile type check. Review the
changed screens in both light and dark device modes.
