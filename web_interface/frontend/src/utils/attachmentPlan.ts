import { AttachmentExecutionPlan, AttachmentExecutionPlanItem, ChatAttachment } from '../types';

type Language = 'zh' | 'en';

interface BuildAttachmentExecutionPlanInput {
  attachments: ChatAttachment[];
  selectedModelSupportsImages: boolean;
  language: Language;
}

function normalizeParseStatus(attachment: ChatAttachment): string {
  return String(attachment.parse_status || 'unknown').trim() || 'unknown';
}

function inferTransportRole(
  attachment: ChatAttachment,
  selectedModelSupportsImages: boolean,
): Omit<AttachmentExecutionPlanItem, 'id' | 'filename'> {
  const parseStatus = normalizeParseStatus(attachment);
  const isImage = Boolean(attachment.is_image);
  const hasVisibleText = parseStatus === 'parsed' && (attachment.visible_text_chars || 0) > 0;
  const toolUsable = Boolean(attachment.file_path || attachment.url);

  if (isImage && selectedModelSupportsImages) {
    return {
      is_image: true,
      parse_status: parseStatus,
      transport_role: 'visual_model',
      transport_reason: 'multimodal_image_input',
      model_visible_on_current_turn: true,
      tool_usable_on_current_turn: toolUsable,
      will_send_image_data: true,
      will_send_attachment_record: true,
    };
  }

  if (hasVisibleText) {
    return {
      is_image: isImage,
      parse_status: parseStatus,
      transport_role: 'text_context',
      transport_reason: 'parsed_text_visible_to_model',
      model_visible_on_current_turn: true,
      tool_usable_on_current_turn: toolUsable,
      will_send_image_data: false,
      will_send_attachment_record: true,
    };
  }

  if (toolUsable) {
    return {
      is_image: isImage,
      parse_status: parseStatus,
      transport_role: 'tool_grounding',
      transport_reason: isImage ? 'image_attachment_for_tool_grounding' : 'file_attachment_for_tool_grounding',
      model_visible_on_current_turn: false,
      tool_usable_on_current_turn: true,
      will_send_image_data: false,
      will_send_attachment_record: true,
    };
  }

  return {
    is_image: isImage,
    parse_status: parseStatus,
    transport_role: 'metadata_only',
    transport_reason: 'metadata_only_attachment',
    model_visible_on_current_turn: false,
    tool_usable_on_current_turn: false,
    will_send_image_data: false,
    will_send_attachment_record: true,
  };
}

function buildSummaryLabel(plan: AttachmentExecutionPlan, language: Language): string {
  const parts: string[] = [];

  if (plan.has_visual_model_input) {
    parts.push(language === 'zh' ? '含视觉输入' : 'visual input');
  }
  if (plan.has_text_context_input) {
    parts.push(language === 'zh' ? '含文本上下文' : 'text context');
  }
  if (plan.has_tool_grounding_input) {
    parts.push(language === 'zh' ? '含工具可用附件' : 'tool grounding');
  }
  if (plan.has_metadata_only_input) {
    parts.push(language === 'zh' ? '含仅元数据附件' : 'metadata only');
  }

  if (parts.length === 0) {
    return language === 'zh' ? '无附件' : 'No attachments';
  }

  return language === 'zh'
    ? `本轮附件: ${parts.join(' / ')}`
    : `Attachments this turn: ${parts.join(' / ')}`;
}

export function buildAttachmentExecutionPlan({
  attachments,
  selectedModelSupportsImages,
  language,
}: BuildAttachmentExecutionPlanInput): AttachmentExecutionPlan {
  const items = attachments.map((attachment, index) => {
    const inferred = inferTransportRole(attachment, selectedModelSupportsImages);
    return {
      id: `${attachment.file_path || attachment.url || attachment.filename || 'attachment'}-${index}`,
      filename: attachment.original_filename || attachment.filename,
      ...inferred,
    } satisfies AttachmentExecutionPlanItem;
  });

  const plan: AttachmentExecutionPlan = {
    items,
    has_visual_model_input: items.some((item) => item.transport_role === 'visual_model'),
    has_text_context_input: items.some((item) => item.transport_role === 'text_context'),
    has_tool_grounding_input: items.some((item) => item.transport_role === 'tool_grounding'),
    has_metadata_only_input: items.some((item) => item.transport_role === 'metadata_only'),
    summary_label: '',
  };

  plan.summary_label = buildSummaryLabel(plan, language);
  return plan;
}

export function getAttachmentTransportRoleLabel(
  role: AttachmentExecutionPlanItem['transport_role'],
  language: Language,
): string {
  if (language === 'zh') {
    switch (role) {
      case 'visual_model':
        return '视觉输入';
      case 'text_context':
        return '文本上下文';
      case 'tool_grounding':
        return '工具可用';
      default:
        return '仅元数据';
    }
  }

  switch (role) {
    case 'visual_model':
      return 'Visual input';
    case 'text_context':
      return 'Text context';
    case 'tool_grounding':
      return 'Tool grounding';
    default:
      return 'Metadata only';
  }
}
