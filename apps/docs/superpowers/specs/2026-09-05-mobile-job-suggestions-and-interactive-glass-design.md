# Mobile Job Suggestions and Interactive Glass Design

## Objective

Match the existing web job-description suggestions on mobile and make native
Liquid Glass treat each control and its visible content as one interactive
surface.

## Job-description suggestions

The job-description screen will reuse the personality screen's horizontal
selector design, selected-state colors, spacing, accessibility semantics, and
keyboard-driven position animation. It will show the three suggestions already
used by `origin/web/dev/job-description-pills`:

- Teach me a language
- Track my finances
- Manage my calendar

Selecting a suggestion replaces the job-description draft. The selected chip is
the suggestion whose text equals the trimmed draft. Users can edit the resulting
text normally. The row moves to the same keyboard-open position as the personality
row and changes position without JavaScript-thread layout animation.

The job screen will also reuse the personality help trigger treatment. Its help
copy will explain that the Ally's job describes what it handles and that a
suggestion is only a starting point.

## Interactive Liquid Glass

The shared Liquid Glass renderer will support optional child content. On
supported iOS versions, those children render inside the native `GlassView`; on
fallback platforms they render inside the existing regular `View` treatment.

The onboarding back chevron will become glass content instead of a separate
sibling. This lets the native held interaction deform and move the circle and
chevron as one control without custom drag math.

The chat composer input and send control will become content of the same native
glass surface. This gives the whole composer one Liquid Glass interaction host
while preserving text editing, sending, keyboard behavior, dynamic height, and
the regular non-glass fallback.

Reduce Motion continues to disable interactive glass deformation. Reduce
Transparency, unsupported iOS versions, Android, and the development regular-UI
override continue to use the existing fallback.

## Google sign-in finding

The latest web flow asks Cloud for a Google authorization URL using a validated
Interface return path and then navigates the browser to that URL. It does not
contain a registered native return URI or the mobile manual-code mode.

The integrated mobile flow already supports the intended temporary Expo Go path:
Google opens in the browser, Cloud displays a short-lived single-use code, and the
user pastes that code into the app. Enabling it still requires the exact HTTPS
return URI registered by Cloud plus
`EXPO_PUBLIC_NATIVE_AUTH_COMPLETION_MODE=manual_code`. No URI will be guessed.

## Validation

- Verify suggestion selection, editing, selected state, keyboard-open placement,
  and reduced-motion behavior.
- Verify back-button tap and held deformation on iOS 26+; the chevron must remain
  visually attached to the glass.
- Verify chat input focus, typing, scrolling, sending, keyboard movement, and
  native glass response on iOS 26+.
- Run focused component tests, the complete mobile Vitest project, mobile
  typecheck, mobile lint, and `git diff --check`.
