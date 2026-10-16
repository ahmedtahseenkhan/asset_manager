import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import clsx from 'clsx';

/** Dialog rendered into <body>, so backdrop-blurred cards can't trap the overlay. Escape closes. */
export default function Modal({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: React.ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[100]" onClick={onClose}>
      <div className={clsx('bg-slate-900 border border-slate-700 rounded-2xl w-full p-6 shadow-2xl max-h-[90vh] overflow-y-auto',
        wide ? 'max-w-4xl' : 'max-w-xl')} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-bold text-slate-50">{title}</h2>
          <button onClick={onClose} className="p-1.5 text-slate-500 hover:text-slate-50 rounded" aria-label="Close"><X className="w-5 h-5" /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
