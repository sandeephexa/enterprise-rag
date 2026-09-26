import { z } from 'zod';

const number = z.number().finite();
export const EvidenceSchema = z.object({ chunk_id: z.string(), quote: z.string() });
export const ClaimSchema = z.object({ text: z.string(), evidence: z.array(EvidenceSchema) });
export const CitationSchema = z.object({
  number: number, claim_index: number, chunk_id: z.string(), document_id: z.string(),
  version: z.string(), source: z.string(), title: z.string(), quote: z.string(), start: number, end: number,
});
export const HitSchema = z.object({
  chunk: z.object({ id: z.string(), document_id: z.string(), version: z.string(), source: z.string(),
    title: z.string(), text: z.string(), start: number, end: number, groups: z.array(z.string()) }),
  fusion_score: number, rerank_score: number.nullable(),
});
export const AnswerSchema = z.object({
  request_id: z.string(), trace_id: z.string(), status: z.enum(['answered', 'abstained', 'review']),
  answer: z.string(), claims: z.array(ClaimSchema), citations: z.array(CitationSchema),
  contexts: z.array(HitSchema), review_reasons: z.array(z.string()), faithfulness: number.nullable(),
  usage: z.object({ input_tokens: number, output_tokens: number, known_cost_usd: number,
    reserved_cost_usd: number, uncertain_attempts: number, attempts: number }),
  latency_ms: number, stage_ms: z.record(z.string(), number), mode: z.enum(['live', 'demo']),
});
export const ReviewSchema = z.object({
  request_id: z.string(),
  answer: z.object({ question: z.string(), answer: AnswerSchema,
    verified_draft: z.object({ claims: z.array(ClaimSchema), abstain: z.boolean() }).nullable(),
    submitted_by: z.string() }),
  state: z.enum(['pending', 'approve', 'reject']),
  decision: z.object({ decision: z.enum(['approve', 'reject']), note: z.string(),
    reviewed_by: z.string(), reviewed_at: z.string() }).nullable(),
});
export const DocumentSchema = z.object({
  id: z.string().regex(/^[A-Za-z0-9_.-]{1,100}$/, 'Use 1–100 letters, numbers, dots, underscores or hyphens.'),
  title: z.string().min(1).max(200), source: z.string().min(1).max(500).refine(s => /^(https:\/\/|urn:)/.test(s), 'Use an HTTPS source or URN.'),
  text: z.string().min(1).max(200000), groups: z.array(z.string().min(1)).min(1).max(50),
}).strict();
export const IngestSchema = z.object({ documents: z.array(DocumentSchema).min(1).max(20) }).strict()
  .refine(batch => new Set(batch.documents.map(d => d.id)).size === batch.documents.length, 'Document IDs must be unique.');

export type Answer = z.infer<typeof AnswerSchema>;
export type Citation = z.infer<typeof CitationSchema>;
export type Hit = z.infer<typeof HitSchema>;
export type Review = z.infer<typeof ReviewSchema>;
export type IngestBatch = z.infer<typeof IngestSchema>;
export type Health = { status: string; mode: 'live' | 'demo' };
