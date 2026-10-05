export type GreenLogoBumpState = {
  active: boolean;
  greenTravelFactor: number;
  greenRotationDeg: number;
  greenScaleX: number;
  greenScaleY: number;
};

const REST_STATE: GreenLogoBumpState = {
  active: false,
  greenTravelFactor: 0,
  greenRotationDeg: 0,
  greenScaleX: 1,
  greenScaleY: 1,
};

export function getGreenLogoBumpState(_frame: number): GreenLogoBumpState {
  'worklet';

  return REST_STATE;
}
