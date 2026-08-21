export function dismissKeyboard(dismiss: () => void) {
  dismiss();
}

export function shouldDismissKeyboardForTouch(
  touchTarget: unknown,
  focusedInput: unknown,
  focusedInputTag?: number | null,
) {
  return (
    touchTarget !== focusedInput &&
    (focusedInputTag == null || String(touchTarget) !== String(focusedInputTag))
  );
}
