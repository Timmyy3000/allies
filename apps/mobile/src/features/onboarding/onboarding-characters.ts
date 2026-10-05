export type AllyColor = 'blue' | 'yellow' | 'green' | 'pink';
export type AllyIdentity = 'rolly' | 'boxy' | 'rocky' | 'ghosty';
export type FloatingAlly = {
  color: AllyColor;
  identity: AllyIdentity;
  tint: string;
  size: number;
  top: `${number}%`;
  left?: `${number}%`;
  right?: `${number}%` | number;
};

export const FLOATING_ALLIES = [
  {
    color: 'blue',
    identity: 'rolly',
    tint: '#3446E9',
    size: 34,
    top: '32%',
    left: '25%',
  },
  {
    color: 'yellow',
    identity: 'boxy',
    tint: '#FBE65F',
    size: 33,
    top: '16%',
    right: '17%',
  },
  {
    color: 'green',
    identity: 'rocky',
    tint: '#12C25B',
    size: 34,
    top: '72%',
    left: '29%',
  },
  {
    color: 'pink',
    identity: 'ghosty',
    tint: '#FD304F',
    size: 35,
    top: '67%',
    right: -7,
  },
] as const satisfies readonly FloatingAlly[];
