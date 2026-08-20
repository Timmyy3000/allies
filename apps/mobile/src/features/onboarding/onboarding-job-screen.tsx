import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

type OnboardingJobScreenProps = {
  jobDescription: string;
  onJobDescriptionChange: (value: string) => void;
};

export function OnboardingJobScreen({
  jobDescription,
  onJobDescriptionChange,
}: OnboardingJobScreenProps) {
  const [isFocused, setIsFocused] = useState(false);
  const remaining = 200 - jobDescription.length;
  const filled = jobDescription.trim().length > 0;

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.root}>
      <View style={styles.editorStack}>
        <View style={[styles.editorCard, isFocused && styles.editorCardFocused]}>
          <TextInput
            accessibilityLabel="Ally job description"
            autoCorrect
            maxLength={200}
            multiline
            onBlur={() => setIsFocused(false)}
            onChangeText={onJobDescriptionChange}
            onFocus={() => setIsFocused(true)}
            placeholder="What do I handle for you?"
            placeholderTextColor="#A8A8A8"
            scrollEnabled
            style={styles.input}
            textAlignVertical="top"
            value={jobDescription}
          />
        </View>
        <Text style={styles.counter}>
          {filled ? `${remaining} characters left` : '200 character limit'}
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  counter: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    letterSpacing: -0.45,
    lineHeight: 18,
    marginTop: 18,
    textAlign: 'center',
  },
  editorCard: {
    backgroundColor: '#F3F3F3',
    borderRadius: 20,
    height: 250,
    overflow: 'hidden',
  },
  editorCardFocused: {
    backgroundColor: '#F1F1F1',
  },
  editorStack: {
    marginTop: 'auto',
    paddingBottom: 17,
  },
  input: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: false,
    letterSpacing: -0.48,
    lineHeight: 22,
    minHeight: 250,
    paddingHorizontal: 14,
    paddingTop: 18,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
});
