import type { IngestBatch } from './api/schemas';
export const SAMPLE_DOCUMENTS: IngestBatch = { documents: [
  { id: 'support', title: 'Enterprise support policy', source: 'urn:acme:support:v1', groups: ['staff'], text: 'Enterprise support is available 24 hours a day. Tickets receive a response within 2 hours.' },
  { id: 'billing', title: 'Billing policy', source: 'urn:acme:billing:v1', groups: ['staff'], text: 'Annual subscriptions are billed in advance. Billing disputes must be submitted within 30 days.' },
  { id: 'onboarding', title: 'Onboarding policy', source: 'urn:acme:onboarding:v1', groups: ['staff'], text: 'New employees complete security training within 7 days. Managers approve access requests.' },
] };
export const LOCAL_TEST_TOKEN = 'test-admin-acme-000000000000000001';
