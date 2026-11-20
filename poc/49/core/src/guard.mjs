export const FORBIDDEN = /\b(attach|copy|install|load|pragma|export|create|insert|update|delete|drop|alter|truncate)\b/i;
export function assertReadOnly(sql) {
  if (FORBIDDEN.test(sql)) { const e = new Error('STATEMENT_NOT_ALLOWED'); e.code = e.code ?? 'STATEMENT_NOT_ALLOWED'; throw e; }
  if (!/^\s*select\b/i.test(sql)) { const e = new Error('PARSE_ERROR'); e.code = e.code ?? 'PARSE_ERROR'; throw e; }
  return sql;
}
