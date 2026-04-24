const INVISIBLE_TEXT_PATTERN = /[\ufeff\u200b\u200c\u200d\u2060]/g;

export function stripInvisibleText(value: string): string {
  return value.replace(INVISIBLE_TEXT_PATTERN, '');
}

function sanitizeDisplayValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return stripInvisibleText(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeDisplayValue(item));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        stripInvisibleText(key),
        sanitizeDisplayValue(item),
      ]),
    );
  }
  return value;
}

export function safeStringifyForDisplay(value: unknown): string {
  const sanitized = sanitizeDisplayValue(value);
  if (typeof sanitized === 'string') {
    return sanitized;
  }
  try {
    return JSON.stringify(sanitized, null, 2);
  } catch {
    return stripInvisibleText(String(sanitized));
  }
}

export function formatToolSectionContent(value: unknown): string {
  if (typeof value === 'string') {
    const sanitized = stripInvisibleText(value);
    const trimmed = sanitized.trim();
    if (
      (trimmed.startsWith('{') && trimmed.endsWith('}'))
      || (trimmed.startsWith('[') && trimmed.endsWith(']'))
    ) {
      try {
        return JSON.stringify(sanitizeDisplayValue(JSON.parse(trimmed)), null, 2);
      } catch {
        return sanitized;
      }
    }
    return sanitized;
  }
  return safeStringifyForDisplay(value);
}
