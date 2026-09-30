export type DecisionDraft = { requestId: string; text: string };

/** A refresh can change the selected record; never reuse another review's note. */
export function noteForReview(draft: DecisionDraft | null, requestId?: string): string {
  return draft?.requestId === requestId ? draft?.text ?? '' : '';
}
