import { type Component, type ReactNode } from 'react';
import {
  Keyboard,
  findNodeHandle,
  TextInput,
  View,
  type GestureResponderEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import {
  dismissKeyboard,
  shouldDismissKeyboardForTouch,
} from './keyboard-dismiss';

type KeyboardDismissViewProps = {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function KeyboardDismissView({ children, style }: KeyboardDismissViewProps) {
  const handleTouchEnd = (event: GestureResponderEvent) => {
    const focusedInput = TextInput.State.currentlyFocusedInput();

    if (
      shouldDismissKeyboardForTouch(
        event.nativeEvent.target,
        focusedInput,
        findNodeHandle(focusedInput as unknown as Component),
      )
    ) {
      dismissKeyboard(Keyboard.dismiss);
    }
  };

  return (
    <View onTouchEnd={handleTouchEnd} style={style}>
      {children}
    </View>
  );
}
