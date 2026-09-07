import { useEffect, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';

import { useAnimatedColor } from '@/components/ui/use-animated-color';
import { useTheme } from '@/hooks/use-theme';

import {
  ALLY_NAME_CARET_BLINK_INTERVAL_MS,
  ALLY_NAME_INPUT_LINE_HEIGHT,
  ALLY_NAME_PLACEHOLDER,
} from './onboarding-motion';
import { isAllyNameReady } from './onboarding-state';

const AnimatedTextInput = Animated.createAnimatedComponent(TextInput);

type AllyNameScreenProps = {
  accentColor: string;
  allyName: string;
  onNameChange: (value: string) => void;
  onNext: () => void;
};

export function AllyNameScreen({
  accentColor,
  allyName,
  onNameChange,
  onNext,
}: AllyNameScreenProps) {
  const theme = useTheme();
  const [isInputFocused, setIsInputFocused] = useState(false);
  const canContinue = isAllyNameReady(allyName);
  const animatedAccentColor = useAnimatedColor(accentColor);
  const emptyCaretOpacity = useSharedValue(0);
  const animatedInputStyle = useAnimatedStyle(() => ({
    color: animatedAccentColor.value,
  }));
  const emptyCaretAnimatedStyle = useAnimatedStyle(() => ({
    opacity: emptyCaretOpacity.value,
  }));

  useEffect(() => {
    cancelAnimation(emptyCaretOpacity);

    if (!allyName && isInputFocused) {
      emptyCaretOpacity.set(withRepeat(
        withSequence(
          withTiming(1, { duration: 0 }),
          withDelay(ALLY_NAME_CARET_BLINK_INTERVAL_MS, withTiming(0, { duration: 0 })),
          withDelay(ALLY_NAME_CARET_BLINK_INTERVAL_MS, withTiming(1, { duration: 0 })),
        ),
        -1,
        false,
      ));
    } else {
      emptyCaretOpacity.set(withTiming(0, { duration: 0 }));
    }

    return () => cancelAnimation(emptyCaretOpacity);
  }, [allyName, emptyCaretOpacity, isInputFocused]);

  const handleNext = () => {
    if (canContinue) onNext();
  };

  return (
    <View pointerEvents="box-none" style={styles.root}>
      <View pointerEvents="box-none" style={styles.inputArea}>
        <AnimatedTextInput
          accessibilityLabel="Ally name"
          autoCapitalize="words"
          autoCorrect={false}
          caretHidden={!allyName && isInputFocused}
          onBlur={() => setIsInputFocused(false)}
          onChangeText={onNameChange}
          onFocus={() => setIsInputFocused(true)}
          onSubmitEditing={handleNext}
          returnKeyType="next"
          selectionColor={allyName ? accentColor : 'transparent'}
          style={[styles.input, animatedInputStyle]}
          underlineColorAndroid="transparent"
          value={allyName}
        />
        {!allyName && !isInputFocused ? (
          <Text pointerEvents="none" style={[styles.placeholder, { color: theme.placeholderText }]}>
            {ALLY_NAME_PLACEHOLDER}
          </Text>
        ) : null}
        {!allyName && isInputFocused ? (
          <Animated.View
            pointerEvents="none"
            style={[styles.emptyCaret, emptyCaretAnimatedStyle, { backgroundColor: accentColor }]}
          />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  input: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    letterSpacing: -1,
    includeFontPadding: false,
    lineHeight: ALLY_NAME_INPUT_LINE_HEIGHT,
    minHeight: 40,
    paddingHorizontal: 0,
    paddingVertical: 2,
    textAlign: 'center',
    textAlignVertical: 'center',
    width: '100%',
  },
  inputArea: {
    alignItems: 'center',
    bottom: 0,
    left: '15%',
    justifyContent: 'center',
    position: 'absolute',
    right: '15%',
    top: 0,
  },
  emptyCaret: {
    height: 30,
    left: '50%',
    marginLeft: -0.75,
    marginTop: -15,
    position: 'absolute',
    top: '50%',
    width: 1.5,
  },
  placeholder: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    left: 0,
    letterSpacing: -1,
    lineHeight: ALLY_NAME_INPUT_LINE_HEIGHT,
    marginTop: -(ALLY_NAME_INPUT_LINE_HEIGHT / 2),
    position: 'absolute',
    right: 0,
    textAlign: 'center',
    textAlignVertical: 'center',
    top: '50%',
  },
  root: {
    flex: 1,
    position: 'relative',
  },
});
