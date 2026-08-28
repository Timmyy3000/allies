import { describe, expect, it } from 'vitest';

import { appendReachableAllyId } from './ally-session-index';

describe('createAllySessionIndex', () => {
  it('keeps unique reachable IDs in discovery order and clears them', () => {
    const first = appendReachableAllyId([], 'ally-1');
    const duplicate = appendReachableAllyId(first, 'ally-1');
    expect(appendReachableAllyId(duplicate, ' ally-2 ')).toEqual(['ally-1', 'ally-2']);
  });

  it('does not add blank IDs', () => {
    expect(appendReachableAllyId([], '   ')).toEqual([]);
  });
});
