import { ChatAttachment, ChatSettings } from '../types';

type Language = ChatSettings['language'];
type AttachmentSurface = 'composer' | 'bubble';

export function getAttachmentBodyHiddenNotice(
  language: Language,
  surface: AttachmentSurface = 'composer',
): string {
  if (language === 'zh') {
    return surface === 'bubble'
      ? '\u9644\u4ef6\u6b63\u6587\u5df2\u89e3\u6790\uff0c\u4f46\u4e3a\u907f\u514d\u5728\u6d88\u606f\u6c14\u6ce1\u4e2d\u76f4\u63a5\u6cc4\u9732\u6587\u4ef6\u5168\u6587\uff0c\u8fd9\u91cc\u4ec5\u4fdd\u7559\u89e3\u6790\u72b6\u6001\u4e0e\u5173\u952e\u7edf\u8ba1\uff0c\u4e0d\u5c55\u793a\u6b63\u6587\u3002'
      : '\u9644\u4ef6\u6b63\u6587\u5df2\u89e3\u6790\uff0c\u4f46\u4e3a\u907f\u514d\u754c\u9762\u6cc4\u9732\u5168\u6587\uff0c\u6b64\u5904\u53ea\u663e\u793a\u89e3\u6790\u72b6\u6001\u548c\u5b57\u7b26\u7edf\u8ba1\u3002\u6a21\u578b\u4ecd\u4f1a\u6309\u5f53\u524d\u53ef\u89c1\u8303\u56f4\u4f7f\u7528\u8be5\u9644\u4ef6\u3002';
  }
  return surface === 'bubble'
    ? 'Attachment body text was parsed, but the message bubble hides the file body and keeps only parsing status and key counts.'
    : 'Attachment body text was parsed, but the UI hides the full content to avoid exposing file text. Only parse status and character counts are shown here; the model can still use the currently visible parsed range.';
}

export function getAttachmentNoBodyContextNotice(language: Language): string {
  return language === 'zh'
    ? '\u5f53\u524d\u9644\u4ef6\u4e0d\u4f1a\u4ee5\u6b63\u6587\u6587\u672c\u5f62\u5f0f\u8fdb\u5165\u6a21\u578b\u4e0a\u4e0b\u6587\u3002'
    : 'This attachment will not enter model context as body text.';
}

export function attachmentHasHiddenBodyText(attachment?: ChatAttachment | null): boolean {
  return Boolean(attachment?.preview_text);
}
