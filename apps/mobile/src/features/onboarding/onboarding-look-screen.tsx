import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { Image } from 'expo-image';
import { useEffect, useRef, useState } from 'react';

import { OnboardingAllyPreview } from './onboarding-ally-preview';
import {
  ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN,
  ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING,
  ONBOARDING_LOOK_HINT_ICON_GAP,
  ONBOARDING_LOOK_HINT_ICON_SIZE,
  getOnboardingLookPreviewLayerScales,
} from './onboarding-layout';
import { ALLY_COLORS, ALLY_SHAPES, type AllyColorValue, type AllyShape } from './onboarding-state';

const CAROUSEL_COPY_COUNT = 3;
const AVATAR_SIZE = 160;

type OnboardingLookScreenProps = {
  allyShape: AllyShape;
  hasSwipedAvatar: boolean;
  selectedColor: AllyColorValue | null;
  onColorChange: (color: AllyColorValue) => void;
  onShapeChange: (shape: AllyShape) => void;
  onSwipe: () => void;
};

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}

export function OnboardingLookScreen({
  allyShape,
  hasSwipedAvatar,
  selectedColor,
  onColorChange,
  onShapeChange,
  onSwipe,
}: OnboardingLookScreenProps) {
  const { width: windowWidth } = useWindowDimensions();
  const scrollRef = useRef<ScrollView>(null);
  const positionedViewportRef = useRef(0);
  const [viewportWidth, setViewportWidth] = useState(0);
  const shapeIndex = Math.max(0, ALLY_SHAPES.indexOf(allyShape));
  const [carouselIndex, setCarouselIndex] = useState(ALLY_SHAPES.length + shapeIndex);
  const artworkScale = getOnboardingLookPreviewLayerScales(selectedColor !== null).artwork;
  const pageWidth = viewportWidth || Math.max(1, windowWidth - 28);
  const pageCount = ALLY_SHAPES.length * CAROUSEL_COPY_COUNT;

  useEffect(() => {
    if (!viewportWidth || positionedViewportRef.current === viewportWidth) return;

    scrollRef.current?.scrollTo({
      animated: false,
      x: carouselIndex * viewportWidth,
    });
    positionedViewportRef.current = viewportWidth;
  }, [carouselIndex, viewportWidth]);

  const setShapeForPage = (rawPage: number, shouldMarkSwipe: boolean) => {
    const nextShapeIndex = modulo(rawPage, ALLY_SHAPES.length);
    const nextShape = ALLY_SHAPES[nextShapeIndex];
    const middlePage = ALLY_SHAPES.length + nextShapeIndex;

    setCarouselIndex(middlePage);
    onShapeChange(nextShape);
    if (shouldMarkSwipe) onSwipe();

    if (rawPage !== middlePage) {
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo({
          animated: false,
          x: middlePage * pageWidth,
        });
      });
    }
  };

  const handleScrollEnd = ({
    nativeEvent,
  }: NativeSyntheticEvent<NativeScrollEvent>) => {
    const rawPage = Math.round(nativeEvent.contentOffset.x / pageWidth);
    setShapeForPage(rawPage, rawPage !== carouselIndex);
  };

  const jumpToShape = (nextShapeIndex: number) => {
    const currentShapeIndex = modulo(carouselIndex, ALLY_SHAPES.length);
    let delta = nextShapeIndex - currentShapeIndex;

    if (delta > ALLY_SHAPES.length / 2) delta -= ALLY_SHAPES.length;
    if (delta < -ALLY_SHAPES.length / 2) delta += ALLY_SHAPES.length;

    const nextPage = carouselIndex + delta;
    setCarouselIndex(nextPage);
    onShapeChange(ALLY_SHAPES[nextShapeIndex]);
    onSwipe();
    scrollRef.current?.scrollTo({ animated: true, x: nextPage * pageWidth });
  };

  return (
    <View style={styles.root}>
      <View
        onLayout={({ nativeEvent }) => setViewportWidth(nativeEvent.layout.width)}
        style={styles.carouselFrame}>
        <ScrollView
          contentContainerStyle={{ width: pageWidth * pageCount }}
          horizontal
          onMomentumScrollEnd={handleScrollEnd}
          pagingEnabled
          ref={scrollRef}
          scrollEventThrottle={16}
          showsHorizontalScrollIndicator={false}
          style={styles.carousel}
          bounces={false}>
          {Array.from({ length: pageCount }, (_, index) => {
            const pageShape = ALLY_SHAPES[index % ALLY_SHAPES.length];

            return (
              <View key={`${pageShape}-${index}`} style={[styles.page, { width: pageWidth }]}>
                <OnboardingAllyPreview
                  accessibilityLabel={`${pageShape} Ally shape`}
                  color={selectedColor}
                  identity={pageShape}
                  size={AVATAR_SIZE}
                  artworkScale={artworkScale}
                />
              </View>
            );
          })}
        </ScrollView>
      </View>

      <View accessibilityLabel="Ally shape choices" style={styles.dots}>
        {ALLY_SHAPES.map((shape, index) => {
          const selected = index === shapeIndex;

          return (
            <Pressable
              accessibilityLabel={`Choose ${shape}`}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              hitSlop={8}
              key={shape}
              onPress={() => jumpToShape(index)}
              style={[styles.dot, selected && { backgroundColor: selectedColor ?? '#FF5800' }]}
            />
          );
        })}
      </View>

      {hasSwipedAvatar ? (
        <ScrollView
          contentContainerStyle={styles.colorRowContent}
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.colorRow}>
          {ALLY_COLORS.map((color) => {
            const selected = selectedColor === color;

            return (
              <Pressable
                accessibilityLabel={`Select ${color} for your Ally`}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                key={color}
                onPress={() => onColorChange(color)}
                style={({ pressed }) => [
                  styles.swatch,
                  { backgroundColor: color },
                  pressed && styles.swatchPressed,
                ]}>
                {selected ? <View style={styles.checkmark} /> : null}
              </Pressable>
            );
          })}
        </ScrollView>
      ) : (
        <View style={styles.hintRow}>
          <Image
            accessibilityLabel="Colour picker"
            contentFit="contain"
            source={require('@/assets/allies/icons/paint.svg')}
            style={styles.hintIcon}
          />
          <Text style={styles.hintText}>Swipe then pick a colour</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  carousel: {
    alignSelf: 'stretch',
    flex: 1,
    width: '100%',
  },
  carouselFrame: {
    alignItems: 'center',
    flex: 0,
    height: AVATAR_SIZE,
    justifyContent: 'center',
    marginTop: 48,
    width: '100%',
  },
  checkmark: {
    borderBottomColor: '#FFFFFF',
    borderBottomWidth: 3,
    borderLeftColor: '#FFFFFF',
    borderLeftWidth: 3,
    height: 11,
    transform: [{ rotate: '-45deg' }],
    width: 19,
  },
  colorRow: {
    backgroundColor: 'transparent',
    borderWidth: 0,
    flexGrow: 0,
    marginBottom: ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN,
    marginHorizontal: -14,
    marginTop: 'auto',
  },
  colorRowContent: {
    alignItems: 'center',
    gap: 18,
    paddingHorizontal: ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING,
  },
  dot: {
    backgroundColor: '#F0F0F0',
    borderRadius: 4,
    height: 8,
    marginHorizontal: 2,
    width: 8,
  },
  dots: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
    justifyContent: 'center',
    marginTop: 36,
  },
  hintIcon: {
    height: ONBOARDING_LOOK_HINT_ICON_SIZE,
    width: ONBOARDING_LOOK_HINT_ICON_SIZE,
  },
  hintRow: {
    alignItems: 'center',
    alignSelf: 'center',
    flexDirection: 'row',
    gap: ONBOARDING_LOOK_HINT_ICON_GAP,
    marginBottom: ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN,
    marginTop: 'auto',
  },
  hintText: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    letterSpacing: -0.5,
    lineHeight: 20,
    textAlign: 'center',
  },
  page: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
    overflow: 'hidden',
  },
  swatch: {
    alignItems: 'center',
    borderRadius: 24,
    height: 48,
    justifyContent: 'center',
    width: 48,
  },
  swatchPressed: {
    opacity: 0.76,
  },
});
