import React, { useEffect, useState } from 'react';
import AppModal from './common/AppModal';
import { useI18n } from '../i18n/I18nProvider';
import { ChatAttachment } from '../types';
import {
  coerceJsonSchemaValue,
  getJsonSchemaProperties,
  getJsonSchemaRequired,
  JsonSchemaProperty,
  resolveJsonSchemaType,
} from '../utils/jsonSchema';

const EMPTY_INITIAL_ARGS: Record<string, any> = {};

const resolveAutoFillReasonLabel = (reason: string, t: (key: string, vars?: Record<string, string | number>) => string) => {
  switch (reason) {
    case 'message_text':
      return t('modal.reasonMessageText');
    case 'attachment_url':
      return t('modal.reasonAttachmentUrl');
    case 'attachment_filename':
      return t('modal.reasonAttachmentFilename');
    case 'attachment_path':
      return t('modal.reasonAttachmentPath');
    default:
      return reason;
  }
};

function buildDefaultFormValues(
  properties: Record<string, JsonSchemaProperty>,
  initialArgs: Record<string, any>,
) {
  const nextValues: Record<string, any> = { ...initialArgs };
  Object.entries(properties).forEach(([key, schema]) => {
    if (nextValues[key] !== undefined) {
      return;
    }
    if (schema.default !== undefined) {
      nextValues[key] = schema.default;
    }
  });
  return nextValues;
}

interface ToolConfirmModalProps {
  isOpen: boolean;
  onConfirm: (args: Record<string, any>) => void;
  onCancel: () => void;
  tool: {
    server: string;
    name: string;
    display_name: string;
    description: string;
    parameters?: {
      properties?: Record<string, any>;
      required?: string[];
    };
    input_schema?: {
      properties?: Record<string, any>;
      required?: string[];
    };
  } | null;
  initialArgs?: Record<string, any>;
  suggestedFields?: string[];
  autoFillReasons?: Record<string, string>;
  attachments?: ChatAttachment[];
}

const ToolConfirmModal: React.FC<ToolConfirmModalProps> = ({
  isOpen,
  onConfirm,
  onCancel,
  tool,
  initialArgs = EMPTY_INITIAL_ARGS,
  suggestedFields = [],
  autoFillReasons = {},
  attachments = [],
}) => {
  const { t } = useI18n();
  const [formValues, setFormValues] = useState<Record<string, any>>(initialArgs);
  const [allowThisChat, setAllowThisChat] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    const resolvedSchema = tool?.input_schema || tool?.parameters || {};
    const properties = getJsonSchemaProperties(resolvedSchema);
    setFormValues(buildDefaultFormValues(properties, initialArgs));
    setAllowThisChat(false);
    setValidationError(null);
  }, [initialArgs, tool]);

  const autoFilledFields = new Set(suggestedFields);

  if (!isOpen || !tool) {
    return null;
  }

  const resolvedSchema = tool.input_schema || tool.parameters || {};
  const properties = getJsonSchemaProperties(resolvedSchema);
  const requiredFields = getJsonSchemaRequired(resolvedSchema);
  const propertyEntries = Object.entries(properties) as Array<[string, JsonSchemaProperty]>;
  const requiredMissing = requiredFields.filter((key) => {
    const value = formValues[key];
    return value === undefined || value === null || String(value).trim() === '';
  });
  const canConfirm = requiredMissing.length === 0;

  const schemaSummary = {
    required: requiredFields.length,
    optional: Math.max(propertyEntries.length - requiredFields.length, 0),
  };

  const getAttachmentCandidates = (key: string, schema: JsonSchemaProperty) => {
    if (resolveJsonSchemaType(schema) !== 'string' || attachments.length === 0) {
      return [];
    }
    const normalizedKey = key.toLowerCase();
    const description = String(schema.description || schema.title || '').toLowerCase();
    const preferUrl = normalizedKey === 'url' || normalizedKey === 'uri' || description.includes('url');
    const preferFilename = normalizedKey.includes('filename') || normalizedKey === 'file_name';
    const pathLike =
      normalizedKey === 'path'
      || normalizedKey.endsWith('_path')
      || normalizedKey.endsWith('path')
      || normalizedKey === 'file'
      || normalizedKey === 'source'
      || normalizedKey === 'input'
      || description.includes('path')
      || preferUrl
      || preferFilename;

    if (!pathLike) {
      return [];
    }

    return attachments
      .map((attachment) => {
        const label = attachment.original_filename || attachment.filename;
        let value = '';
        let reason = '';
        if (preferUrl && attachment.url) {
          value = attachment.url;
          reason = t('modal.reasonAttachmentUrl');
        } else if (preferFilename) {
          value = attachment.original_filename || attachment.filename;
          reason = t('modal.reasonAttachmentFilename');
        } else {
          value = attachment.file_path || attachment.url || attachment.filename;
          reason = t('modal.reasonAttachmentPath');
        }
        return value ? { label, value, reason } : null;
      })
      .filter((item): item is { label: string; value: string; reason: string } => Boolean(item));
  };

  const handleConfirm = () => {
    if (!canConfirm) {
      setValidationError(t('modal.requiredMissing', { fields: requiredMissing.join(', ') }));
      return;
    }
    onConfirm({
      ...formValues,
      _allowThisChat: allowThisChat,
    });
    setFormValues({});
    setAllowThisChat(false);
    setValidationError(null);
  };

  const renderField = (key: string, schema: JsonSchemaProperty) => {
    const schemaType = resolveJsonSchemaType(schema);
    const label = schema.title || key;
    const required = requiredFields.includes(key);
    const suggested = autoFilledFields.has(key);
    const value = formValues[key] ?? schema.default ?? (schemaType === 'boolean' ? false : '');
    const autoFillReason = autoFillReasons[key];
    const attachmentCandidates = getAttachmentCandidates(key, schema);
    const baseInputClass = 'w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 dark:border-slate-700 dark:bg-slate-900/70 dark:text-white';

    return (
      <div key={key}>
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
              {label}
              {required && <span className="ml-1 text-red-500">*</span>}
            </label>
            {suggested && (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
                {t('modal.autoFilled')}
              </span>
            )}
          </div>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {schemaType}
          </span>
        </div>

        {schema.enum ? (
          <select
            value={String(value)}
            onChange={(event) => setFormValues((prev) => ({ ...prev, [key]: coerceJsonSchemaValue(schema, event.target.value) }))}
            className={baseInputClass}
          >
            <option value="">{t('modal.selectValue')}</option>
            {schema.enum.map((item) => (
              <option key={String(item)} value={String(item)}>
                {String(item)}
              </option>
            ))}
          </select>
        ) : schemaType === 'boolean' ? (
          <label className="inline-flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(event) => setFormValues((prev) => ({ ...prev, [key]: event.target.checked }))}
              className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            />
            <span>{t('modal.booleanEnabled')}</span>
          </label>
        ) : schemaType === 'object' || schemaType === 'array' ? (
          <textarea
            value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
            onChange={(event) => {
              const raw = event.target.value;
              try {
                setFormValues((prev) => ({ ...prev, [key]: raw.trim() ? JSON.parse(raw) : raw }));
              } catch {
                setFormValues((prev) => ({ ...prev, [key]: raw }));
              }
            }}
            placeholder={schema.description || key}
            rows={4}
            className={baseInputClass}
          />
        ) : (
          <input
            type={schemaType === 'integer' || schemaType === 'number' ? 'number' : 'text'}
            value={value}
            onChange={(event) => setFormValues((prev) => ({ ...prev, [key]: coerceJsonSchemaValue(schema, event.target.value) }))}
            placeholder={schema.description || key}
            className={baseInputClass}
          />
        )}

        {schema.description && (
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{schema.description}</p>
        )}
        {(schema.default !== undefined || attachmentCandidates.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-2">
            {schema.default !== undefined && (
              <button
                type="button"
                onClick={() => setFormValues((prev) => ({ ...prev, [key]: schema.default }))}
                className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                {t('modal.useSchemaDefault')}
              </button>
            )}
            {attachmentCandidates.map((candidate) => (
              <button
                type="button"
                key={`${key}-${candidate.value}`}
                onClick={() => setFormValues((prev) => ({ ...prev, [key]: candidate.value }))}
                className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 transition hover:bg-emerald-100 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200 dark:hover:bg-emerald-900/30"
                title={`${candidate.reason}: ${candidate.value}`}
              >
                {t('modal.useAttachmentCandidate', { file: candidate.label })}
              </button>
            ))}
          </div>
        )}
        {autoFillReason && (
          <p className="mt-1 text-xs leading-5 text-emerald-700 dark:text-emerald-300">
            {t('modal.autoFilledReason', { reason: resolveAutoFillReasonLabel(autoFillReason, t) })}
          </p>
        )}
      </div>
    );
  };

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onCancel}
      title={t('modal.confirmToolCall')}
      description={t('modal.confirmToolDesc')}
      maxWidthClassName="max-w-2xl"
      bodyClassName="p-6"
    >
      <div className="space-y-6">
        <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40">
          <div className="grid gap-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('modal.tool')}</div>
              <div className="mt-1 font-medium text-slate-900 dark:text-white">
                {tool.display_name} ({tool.name})
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('modal.server')}</div>
              <div className="mt-1 font-medium text-slate-900 dark:text-white">{tool.server}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('modal.description')}</div>
              <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">{tool.description || t('app.noDescription')}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 dark:bg-sky-900/20 dark:text-sky-300">
                {t('modal.requiredFields')}: {schemaSummary.required}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                {t('modal.optionalFields')}: {schemaSummary.optional}
              </span>
            </div>
          </div>
        </div>

        {propertyEntries.length > 0 ? (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">{t('modal.arguments')}</h3>
            {suggestedFields.length > 0 && (
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200">
                {t('modal.reviewAutoFilled')}
              </div>
            )}
            {propertyEntries.map(([key, schema]) => renderField(key, schema))}
          </div>
        ) : (
          <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-700 dark:border-sky-800 dark:bg-sky-900/20 dark:text-sky-300">
            {t('modal.noExtraArgs')}
          </div>
        )}

        {validationError && (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
            {validationError}
          </div>
        )}

        <label className="flex items-center space-x-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
          <input
            type="checkbox"
            checked={allowThisChat}
            onChange={(event) => setAllowThisChat(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          />
          <span>{t('modal.allowThisChat')}</span>
        </label>

        <div className="flex items-center justify-end gap-3 border-t border-slate-200 pt-5 dark:border-slate-700">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t('modal.cancel')}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="rounded-2xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('modal.confirm')}
          </button>
        </div>
      </div>
    </AppModal>
  );
};

export default ToolConfirmModal;
