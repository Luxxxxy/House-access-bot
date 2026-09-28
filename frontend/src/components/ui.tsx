import type { ButtonHTMLAttributes, PropsWithChildren } from 'react';

const iconPaths: Record<string, React.ReactNode> = {
  home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-7h6v7"/></>,
  pass: <><path d="M4 6h16v12H4z"/><path d="M8 10h8M8 14h5"/><path d="M7 3v3m10-3v3"/></>,
  profile: <><circle cx="12" cy="8" r="3.5"/><path d="M5 21a7 7 0 0 1 14 0"/></>,
  shield: <><path d="M12 3 20 6v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/><path d="m9 12 2 2 4-4"/></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5m4-1v5l3 2"/></>,
  users: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-1a6 6 0 0 1 12 0v1z"/><path d="M16 5.5a3 3 0 0 1 0 5.8m2 3a5 5 0 0 1 3 4.7v1h-4"/></>,
  guards: <><path d="M12 3 20 6v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/><path d="M12 7v7m0 3h.01"/></>,
  checkpoint: <><path d="M4 21V5l8-2 8 2v16"/><path d="M8 21v-6h8v6M8 8h.01M12 8h.01M16 8h.01"/></>,
  shifts: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  registry: <><path d="M5 3h11l3 3v15H5z"/><path d="M15 3v4h4M8 11h8m-8 4h8m-8 4h5"/></>,
  book: <><path d="M4 4h13a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z"/><path d="M4 17a3 3 0 0 1 3-3h13M8 8h7"/></>,
  settings: <><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"/><path d="m19.4 15 .1.1 1.2 1-1.4 2.4-1.5-.6a8 8 0 0 1-1.5.9L16 20.5h-3l-.4-1.7a8 8 0 0 1-1.5-.9l-1.6.6-1.4-2.4 1.3-1a8 8 0 0 1 0-1.8l-1.3-1 1.4-2.4 1.6.6a8 8 0 0 1 1.5-.9L13 4.9h3l.4 1.7a8 8 0 0 1 1.5.9l1.5-.6 1.4 2.4-1.2 1a8 8 0 0 1-.2 1.8Z"/></>,
  search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/></>,
  building: <><path d="M4 21V5l8-2 8 2v16"/><path d="M8 8h.01M12 8h.01M16 8h.01M8 12h.01M12 12h.01M16 12h.01M10 21v-4h4v4"/></>,
  plus: <><path d="M12 5v14M5 12h14"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>,
  close: <><path d="m6 6 12 12M18 6 6 18"/></>,
  pin: <><path d="m16 3 5 5-4 1-4 4-1 5-2-2-4 4-1-1 4-4-2-2 5-1 4-4z"/></>,
  upload: <><path d="M12 16V4m-4 4 4-4 4 4"/><path d="M5 14v6h14v-6"/></>,
  spark: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></>,
  bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
  logout: <><path d="M10 17l5-5-5-5m5 5H3"/><path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7"/></>,
  phone: <><path d="M7 3H5a2 2 0 0 0-2 2c0 9 7 16 16 16a2 2 0 0 0 2-2v-2l-5-2-2 2a14 14 0 0 1-6-6l2-2z"/></>,
};

export function Icon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  return <svg aria-hidden="true" className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{iconPaths[name] || iconPaths.spark}</svg>;
}

export function Card({ children, className = '' }: PropsWithChildren<{ className?: string }>) {
  return <section className={`card ${className}`}>{children}</section>;
}

export function ActionButton({
  children,
  tone = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'quiet' | 'danger' }) {
  return <button className={`button button--${tone}`} {...props}>{children}</button>;
}

export function SectionTitle({ title, detail }: { title: string; detail?: string }) {
  return <div className="section-title"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div></div>;
}

export function StatusPill({ status, kind = 'visit' }: { status: string; kind?: 'visit' | 'guard' }) {
  const labels: Record<string, string> = {
    ACTIVE: 'Активна', PASSED: 'Прошёл', REJECTED: 'Отклонена', EXPIRED: 'Истекла',
    CANCELLED: 'Отменена', DELETED: 'Удалена',
    VERIFIED: 'Подтверждён', PENDING: 'Ожидает проверки', DEACTIVATED: 'Отключён',
    INVITED: 'Приглашён', REJECTED_GUARD: 'Отклонён',
  };
  const label = status === 'REJECTED' && kind === 'guard' ? 'Отклонён' : labels[status] || 'Статус не указан';
  return <span className={`status status--${status.toLowerCase()}`}>{label}</span>;
}

export function EmptyState({ title, detail, className = '' }: { title: string; detail: string; className?: string }) {
  return <div className={['empty', className].filter(Boolean).join(' ')}><span className="empty__icon"><Icon name="spark"/></span><strong>{title}</strong><p>{detail}</p></div>;
}

export function Notice({ children, onClose }: PropsWithChildren<{ onClose: () => void }>) {
  return <div role="status" className="notice"><span>{children}</span><button aria-label="Закрыть уведомление" onClick={onClose}><Icon name="close" size={18}/></button></div>;
}
