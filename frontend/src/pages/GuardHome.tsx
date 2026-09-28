import { FormEvent, useCallback, useEffect, useState } from 'react';
import { api, json } from '../api';
import type { AuthContext, Visit } from '../types';
import { ActionButton, Card, EmptyState, Icon, StatusPill } from '../components/ui';

type Props = { auth: AuthContext; toast: (text: string) => void; section: string; onNavigate: (section: string) => void; fullName: string; complex: string };
const labels: Record<string, string> = { COURIER: 'Курьер', GUEST: 'Гость', REPAIR: 'Рабочий', OTHER: 'Другое' };

export function GuardHome({ auth, toast, section, fullName, complex }: Props) {
  const [items, setItems] = useState<Visit[]>([]);
  const [history, setHistory] = useState<Visit[]>([]);
  const [q, setQ] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Visit | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [tab, setTab] = useState<'queue' | 'history'>('queue');
  const [busy, setBusy] = useState(false);
  const [checkpoint, setCheckpoint] = useState('');
  const [guardStatus, setGuardStatus] = useState('');
  const [onShift, setOnShift] = useState(false);

  const refresh = useCallback(async () => {
    const query = search ? `?q=${encodeURIComponent(search)}&limit=100` : '?limit=100';
    const [queue, past, profile] = await Promise.all([
      api<{ items: Visit[]; total: number }>(`/guards/queue${query}`, auth),
      api<Visit[]>('/guards/history?limit=100', auth),
      api<{ status: string; on_shift: boolean; checkpoints: { id: string; name: string; on_shift: boolean }[] }>('/guards/me', auth),
    ]);
    setItems(queue.items);
    setHistory(past);
    setGuardStatus(profile.status);
    setOnShift(profile.on_shift);
    setCheckpoint(profile.on_shift ? profile.checkpoints.filter((item) => item.on_shift).map((item) => item.name).join(' · ') : (profile.status === 'PENDING' ? 'Ожидает проверки' : 'Смена сейчас не активна'));
  }, [auth.demoUserId, auth.authorization, search]);

  useEffect(() => {
    refresh().catch((e) => toast(e.message));
    const timer = window.setInterval(() => refresh().catch(() => undefined), 15000);
    const onFocus = () => refresh().catch(() => undefined);
    window.addEventListener('focus', onFocus);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); };
  }, [refresh]);

  async function openDetail(item: Visit) {
    try {
      const detail = await api<Visit>(`/guards/${item.id}`, auth);
      setSelected(detail);
    } catch (e) { toast((e as Error).message); }
  }

  async function decide(status: 'PASSED' | 'REJECTED', rejectReason?: string, targetId?: string) {
    const requestId = targetId || selected?.id;
    if (!requestId || busy) return;
    setBusy(true);
    try {
      await api(`/guards/${requestId}/decision`, auth, json('POST', { status, reason: rejectReason || null }));
      setSelected(null);
      setRejecting(false);
      setReason('');
      toast(status === 'PASSED' ? 'Проход зафиксирован. Житель получит уведомление.' : 'Заявка отклонена. Житель получит причину.');
      await refresh();
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  }

  async function togglePin(item: Visit) {
    try {
      await api(`/guards/${item.id}/pin`, auth, json('PUT', { is_pinned: !item.is_pinned }));
      await refresh();
      toast(item.is_pinned ? 'Заявка откреплена' : 'Заявка закреплена');
    } catch (e) { toast((e as Error).message); }
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setSearch(q.trim());
  }

  const queueCards = items.length ? items.map((visit) => <Card key={visit.id} className="guard-card">
    <div className="visit-card__top"><StatusPill status={visit.status}/><span className="arrival-time">{visit.estimated_arrival_at ? new Date(visit.estimated_arrival_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : 'Время не указано'}</span></div>
    <button className="guard-card__main" onClick={() => openDetail(visit)}><h3>{visit.visitor_name}</h3><p className="visit-card__sub">{labels[visit.visitor_type]}{visit.visitor_car_number ? ` · ${visit.visitor_car_number}` : ''}</p><div className="metadata"><span><Icon name="building" size={13}/>Корпус {visit.building}, кв. {visit.apartment}</span><span>{visit.resident_name}</span></div></button>
    {visit.comment && <p className="comment">{visit.comment}</p>}
    <div className="guard-card__actions"><ActionButton onClick={() => decide('PASSED', undefined, visit.id).catch(() => undefined)}><Icon name="check" size={16}/>Гость прошёл</ActionButton><ActionButton tone="quiet" onClick={() => openDetail(visit)}>Подробнее</ActionButton><button className={`pin-button ${visit.is_pinned ? 'pin-button--on' : ''}`} aria-label={visit.is_pinned ? 'Снять закрепление' : 'Закрепить заявку'} onClick={() => togglePin(visit)}><Icon name="pin" size={17}/></button></div>
  </Card>) : <EmptyState className="empty--queue" title="Новых заявок нет" detail="Когда жилец оформит пропуск, он появится здесь. Очередь обновляется каждые 15 секунд."/>;
  const historyCards = history.length ? history.map((visit) => <Card key={visit.id} className="visit-card visit-card--compact"><div className="visit-card__top"><StatusPill status={visit.status}/><span className="muted">{visit.resolved_at ? new Date(visit.resolved_at).toLocaleString('ru-RU') : ''}</span></div><h3>{visit.visitor_name}</h3><p className="visit-card__sub">{labels[visit.visitor_type]} · корпус {visit.building}, кв. {visit.apartment}</p>{visit.rejection_reason && <p className="reason">Причина: {visit.rejection_reason}</p>}</Card>) : <EmptyState title="История пуста" detail="Здесь появятся обработанные заявки."/>;

  return <div className="guard-screen">
    {section === 'queue' && <>
      <div className="welcome-row"><div><p className="eyebrow">КПП · РАБОЧЕЕ МЕСТО</p><h1>Заявки</h1></div><div className="welcome-mark welcome-mark--guard"><Icon name="shield" size={23}/></div></div>
      <Card className="shift-banner"><span className={onShift ? 'live-dot' : 'live-dot live-dot--off'}/><div><strong>{onShift ? 'Смена активна' : 'Смена не активна'}</strong><p>{checkpoint} · список обновляется автоматически</p></div><span className="shift-banner__count">{items.length}</span></Card>
      <form className="search-box" onSubmit={submitSearch}><Icon name="search" size={19}/><input aria-label="Поиск заявок" placeholder="ФИО, машина, квартира..." value={q} onChange={(e) => setQ(e.target.value)}/><button type="submit">Найти</button></form>
      <div className="tabs" role="tablist"><button className={tab === 'queue' ? 'tab tab--active' : 'tab'} onClick={() => setTab('queue')}>Активные <span>{items.length}</span></button><button className={tab === 'history' ? 'tab tab--active' : 'tab'} onClick={() => setTab('history')}>История</button></div>
      <div className="stack">{tab === 'queue' ? queueCards : historyCards}</div>
    </>}
    {section === 'history' && <><div className="welcome-row"><div><p className="eyebrow">КПП · ЗАПИСИ</p><h1>История</h1></div><div className="welcome-mark welcome-mark--guard"><Icon name="history" size={23}/></div></div><div className="stack">{historyCards}</div></>}
    {section === 'profile' && <><div className="welcome-row"><div><p className="eyebrow">АККАУНТ ОХРАНЫ</p><h1>Профиль</h1></div><div className="welcome-mark welcome-mark--guard"><Icon name="profile" size={23}/></div></div><Card className="guard-profile-card"><span className="guard-profile-card__avatar"><Icon name="shield" size={25}/></span><div><h2>{fullName}</h2><p>{complex}</p><StatusPill status={guardStatus} kind="guard"/></div></Card><Card><div className="guard-profile-detail"><span className="hero-icon"><Icon name="checkpoint" size={19}/></span><span><strong>Назначенный КПП</strong><small>{checkpoint}</small></span></div><div className="guard-profile-detail"><span className="hero-icon"><Icon name="shifts" size={19}/></span><span><strong>Состояние смены</strong><small>{onShift ? 'Смена активна' : 'Смена не активна'}</small></span></div></Card></>}

    {selected && <div className="modal-backdrop" role="presentation" onClick={() => { setSelected(null); setRejecting(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="detail-title" onClick={(e) => e.stopPropagation()}>
      <button className="modal-close" aria-label="Закрыть" onClick={() => { setSelected(null); setRejecting(false); }}><Icon name="close" size={18}/></button>
      <p className="eyebrow">ЗАЯВКА НА ПРОПУСК</p><h2 id="detail-title">{selected.visitor_name}</h2><div className="detail-grid"><div><small>Тип посетителя</small><strong>{labels[selected.visitor_type]}</strong></div><div><small>КПП</small><strong>{selected.checkpoint}</strong></div><div><small>Квартира</small><strong>Корпус {selected.building} · {selected.apartment}</strong></div><div><small>Житель</small><strong>{selected.resident_name}</strong></div><div><small>Контакт</small><strong>{selected.resident_contact}</strong></div><div><small>Автомобиль</small><strong>{selected.visitor_car_number || 'Не указан'}</strong></div><div><small>Прибытие</small><strong>{selected.estimated_arrival_at ? new Date(selected.estimated_arrival_at).toLocaleString('ru-RU') : 'Не указано'}</strong></div></div>
      {selected.comment && <div className="detail-note">{selected.comment}</div>}
      {!rejecting ? <div className="modal-actions"><ActionButton tone="quiet" onClick={() => setRejecting(true)}>Отклонить</ActionButton><ActionButton onClick={() => decide('PASSED')} disabled={busy}>{busy ? 'Сохраняем…' : 'Гость прошёл'}</ActionButton></div> : <form onSubmit={(e) => { e.preventDefault(); decide('REJECTED', reason).catch(() => undefined); }}><label>Причина отклонения<input autoFocus required minLength={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Например, данные не совпали"/></label><div className="modal-actions"><ActionButton type="button" tone="quiet" onClick={() => setRejecting(false)}>Назад</ActionButton><ActionButton tone="danger" disabled={busy || !reason.trim()}>{busy ? 'Сохраняем…' : 'Подтвердить отказ'}</ActionButton></div></form>}
    </div></div>}
  </div>;
}
