import { describe, expect, it } from 'vitest';
import { noteForReview } from '../src/reviewState';

describe('decision note ownership', () => {
  it('does not apply an old note when refresh selects a different review', () => {
    const draft = { requestId: 'old-review', text: 'Approve this supported answer.' };
    expect(noteForReview(draft, 'old-review')).toBe(draft.text);
    expect(noteForReview(draft, 'new-review')).toBe('');
    expect(noteForReview(draft, undefined)).toBe('');
    expect(noteForReview(null, 'new-review')).toBe('');
  });
});
