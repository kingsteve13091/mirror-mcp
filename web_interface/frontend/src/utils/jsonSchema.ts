export type JsonSchemaProperty = {
  title?: string;
  description?: string;
  type?: string | string[];
  enum?: Array<string | number | boolean>;
  default?: unknown;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  items?: JsonSchemaProperty;
  anyOf?: JsonSchemaProperty[];
  oneOf?: JsonSchemaProperty[];
  allOf?: JsonSchemaProperty[];
};

export type JsonSchemaObject = {
  type?: string | string[];
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  anyOf?: JsonSchemaProperty[];
  oneOf?: JsonSchemaProperty[];
  allOf?: JsonSchemaProperty[];
};

const pickNonNullType = (rawType: unknown) => {
  if (Array.isArray(rawType)) {
    const selected = rawType.find((item) => item !== 'null');
    return typeof selected === 'string' && selected.trim() ? selected.trim() : '';
  }
  return typeof rawType === 'string' && rawType.trim() ? rawType.trim() : '';
};

export function resolveJsonSchemaType(schema: JsonSchemaProperty | Record<string, any> | null | undefined): string {
  if (!schema || typeof schema !== 'object') {
    return 'string';
  }

  const directType = pickNonNullType((schema as JsonSchemaProperty).type);
  if (directType) {
    return directType;
  }

  for (const unionKey of ['anyOf', 'oneOf', 'allOf'] as const) {
    const variants = (schema as JsonSchemaProperty)[unionKey];
    if (!Array.isArray(variants)) {
      continue;
    }
    const resolved = variants
      .map((variant) => resolveJsonSchemaType(variant))
      .find((variantType) => variantType && variantType !== 'null');
    if (resolved) {
      return resolved;
    }
  }

  if ((schema as JsonSchemaProperty).properties) {
    return 'object';
  }
  if ((schema as JsonSchemaProperty).items) {
    return 'array';
  }
  return 'string';
}

export function getJsonSchemaProperties(schema: JsonSchemaObject | Record<string, any> | null | undefined) {
  const properties = schema?.properties;
  return properties && typeof properties === 'object' ? properties : {};
}

export function getJsonSchemaRequired(schema: JsonSchemaObject | Record<string, any> | null | undefined) {
  const required = schema?.required;
  return Array.isArray(required) ? required.map(String) : [];
}

export function coerceJsonSchemaValue(schema: JsonSchemaProperty | Record<string, any>, rawValue: string | boolean) {
  const schemaType = resolveJsonSchemaType(schema);
  if (schemaType === 'boolean') {
    return Boolean(rawValue);
  }
  if (schemaType === 'integer') {
    const trimmed = String(rawValue).trim();
    if (!trimmed) {
      return '';
    }
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isNaN(parsed) ? rawValue : parsed;
  }
  if (schemaType === 'number') {
    const trimmed = String(rawValue).trim();
    if (!trimmed) {
      return '';
    }
    const parsed = Number.parseFloat(trimmed);
    return Number.isNaN(parsed) ? rawValue : parsed;
  }
  return rawValue;
}

export function pruneEmptyOptionalArgs(
  schema: JsonSchemaObject | Record<string, any> | null | undefined,
  args: Record<string, any>,
) {
  const required = new Set(getJsonSchemaRequired(schema));
  return Object.entries(args || {}).reduce<Record<string, any>>((acc, [key, value]) => {
    if (!required.has(key)) {
      if (value === undefined || value === null) {
        return acc;
      }
      if (typeof value === 'string' && value.trim() === '') {
        return acc;
      }
    }
    acc[key] = value;
    return acc;
  }, {});
}
