import React, { useEffect, useId, useMemo, useRef } from 'react';

interface AppModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  maxWidthClassName?: string;
  panelClassName?: string;
  bodyClassName?: string;
  closeOnBackdrop?: boolean;
  headerActions?: React.ReactNode;
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const AppModal: React.FC<AppModalProps> = ({
  isOpen,
  onClose,
  title,
  description,
  children,
  maxWidthClassName = 'max-w-4xl',
  panelClassName = '',
  bodyClassName = '',
  closeOnBackdrop = true,
  headerActions,
}) => {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  const describedBy = useMemo(() => (description ? descriptionId : undefined), [description, descriptionId]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    previousActiveElement.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = panel?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    const initialFocus = focusable && focusable.length > 0 ? focusable[0] : panel;
    initialFocus?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== 'Tab' || !panel) {
        return;
      }

      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        .filter((item) => !item.hasAttribute('disabled') && item.tabIndex !== -1);

      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = '';
      previousActiveElement.current?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (closeOnBackdrop && event.target === event.currentTarget) {
          onClose();
        }
      }}
      aria-hidden={false}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={`flex max-h-[88vh] w-full flex-col overflow-hidden rounded-[28px] border border-white/25 bg-white/95 shadow-2xl outline-none dark:border-slate-700/50 dark:bg-slate-900/95 ${maxWidthClassName} ${panelClassName}`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200/80 px-6 py-5 dark:border-slate-700/70">
          <div>
            <h2 id={titleId} className="text-xl font-semibold text-slate-900 dark:text-white">{title}</h2>
            {description && (
              <p id={descriptionId} className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>
            )}
          </div>
          {headerActions}
        </div>
        <div className={`flex-1 overflow-y-auto ${bodyClassName}`}>{children}</div>
      </div>
    </div>
  );
};

export default AppModal;
