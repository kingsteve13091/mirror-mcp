import { messages } from './messages';

type FlatKeys = Record<string, string>;

function flattenMessageTree(input: Record<string, unknown>, prefix = ''): FlatKeys {
  return Object.entries(input).reduce<FlatKeys>((acc, [key, value]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      acc[nextKey] = value;
      return acc;
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(acc, flattenMessageTree(value as Record<string, unknown>, nextKey));
    }
    return acc;
  }, {});
}

describe('messages dictionary consistency', () => {
  it('keeps zh and en message keys aligned', () => {
    const zhKeys = Object.keys(flattenMessageTree(messages.zh));
    const enKeys = Object.keys(flattenMessageTree(messages.en));

    expect(enKeys).toEqual(zhKeys);
  });
});
