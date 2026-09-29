import { z } from 'zod';

export const UploadLimitsSchema = z.object({
  extensions: z.array(z.string()), max_file_bytes: z.number().positive(),
  max_extracted_chars: z.number().positive(), max_pdf_pages: z.number().positive(),
  max_excel_sheets: z.number().positive(), parse_timeout_s: z.number().positive(),
});
export const UploadResultSchema = z.object({
  document_id: z.string(), source: z.string(), indexed_chunks: z.number().int().nonnegative(),
  extracted_characters: z.number().int().nonnegative(), warnings: z.array(z.string()),
});
export type UploadLimits = z.infer<typeof UploadLimitsSchema>;
export type UploadResult = z.infer<typeof UploadResultSchema>;

export function validateFile(file: Pick<File, 'name' | 'size'>, limits: UploadLimits): string | null {
  const extension = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!limits.extensions.includes(extension)) return `Unsupported format. Choose ${limits.extensions.join(', ')}.`;
  if (!file.size) return 'The file is empty.';
  if (file.size > limits.max_file_bytes) return `File exceeds ${(limits.max_file_bytes / 1048576).toFixed(0)} MiB.`;
  if (file.name.length > 255 || /[\u0000-\u001f]/.test(file.name)) return 'File name is invalid or too long.';
  return null;
}
