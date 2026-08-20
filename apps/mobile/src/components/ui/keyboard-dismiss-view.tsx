import { type ReactNode } from 'react';
import {
  Keyboard,
  TouchableWithoutFeedback,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { dismissKeyboard } from './keyboard-dismiss';

type KeyboardDismissViewProps = {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function KeyboardDismissView({ children, style }: KeyboardDismissViewProps) {
  return (
    <TouchableWithoutFeedback onPress={() => dismissKeyboard(Keyboard.dismiss)}>
      <View style={style}>{children}</View>
    </TouchableWithoutFeedback>
  );
}
