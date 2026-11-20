// Server-side guard: the bridge must never become a SQL injection surface.
const FORBIDDEN = /\b(attach|copy|install|load|pragma|export|create|insert|update|delete|drop|alter|truncate)\b/i;
export function assertReadOnly(sql) {
  if (FORBIDDEN.test(sql)) {
    const err = new Error('STATEMENT_NOT_ALLOWED');
    err.code = 'STATEMENT_NOT_ALLOWED';
    throw err;
  }
  if (!/^\s*select\b/i.test(sql)) {
    const err = new Error('PARSE_ERROR');
    err.code = 'PARSE_ERROR';
    throw err;
  }
  return sql;
}
