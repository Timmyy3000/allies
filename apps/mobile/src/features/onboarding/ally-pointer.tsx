import Svg, { Path } from 'react-native-svg';
import { StyleSheet, View } from 'react-native';

const POINTER_PATH =
  'M25.8723 8.1633C28.7683 9.2356 28.7523 13.3397 25.8445 14.3857L17.6873 17.3219C17.5143 17.3847 17.3813 17.5195 17.3221 17.6847L14.3844 25.8445C13.3383 28.7519 9.2337 28.7685 8.1614 25.8727L0.2632 4.6066C0.225 4.5034 0.1859 4.4006 0.1532 4.2955C-0.639 1.755 1.7753-0.6558 4.3218 0.1625C4.4342 0.1986 4.5445 0.2414 4.6553 0.2824L25.8723 8.1633Z';

type AllyPointerProps = {
  color: string;
  rotation: number;
  size?: number;
};

export function AllyPointer({ color, rotation, size = 27 }: AllyPointerProps) {
  return (
    <View
      pointerEvents="none"
      style={[
        styles.container,
        { width: size, height: size, transform: [{ rotate: `${rotation + 135}deg` }] },
      ]}>
      <Svg height={size} viewBox="0 0 28.035 28.035" width={size}>
        <Path d={POINTER_PATH} fill={color} />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
