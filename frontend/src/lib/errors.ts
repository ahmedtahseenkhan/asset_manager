/** Readable message from an API error (FastAPI `detail`, our `message`, or the transport error). */
export function errorText(err: unknown): string {
  const e = err as { message?: string; response?: { data?: unknown } };
  const body = e?.response?.data as { detail?: unknown; message?: string } | Blob | undefined;
  if (body instanceof Blob) return 'Request failed';
  const detail = body?.detail ?? body?.message ?? e?.message ?? 'Request failed';
  return typeof detail === 'string' ? detail : JSON.stringify(detail);
}
