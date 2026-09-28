import { FormEvent, useEffect, useState } from 'react';
import { api, json } from '../api';
import type { Apartment, AuthContext, Visit } from '../types';
import { ActionButton, Card, EmptyState, Icon, SectionTitle, StatusPill } from '../components/ui';

type Checkpoint = { id: string; name: string };
type Props = { auth: AuthContext; apartments: Apartment[]; fullName: string; contact?: string | null; onProfileChanged: () => Promise<void>; toast: (text: string) => void; section: string; onNavigate: (section: string) => void };
const visitTypes = { COURIER: 'Курьер', GUEST: 'Гость', REPAIR: 'Рабочий', OTHER: 'Другое' };

export function ResidentHome({ auth, apartments, fullName, contact, onProfileChanged, toast, section, onNavigate }: Props) {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [active, setActive] = useState<Visit[]>([]);
  const [history, setHistory] = useState<Visit[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [formStep, setFormStep] = useState<'type' | 'details'>('type');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'active' | 'history'>('active');
  const [showApartmentForm, setShowApartmentForm] = useState(false);
  const [apartmentDraft, setApartmentDraft] = useState({ building: '', apartment: '' });
  const [draft, setDraft] = useState({
    apartment_id: apartments[0]?.id || '', checkpoint_id: '', visitor_type: 'COURIER',
    visitor_name: '', visitor_car_number: '', resident_contact: contact || '', arrival: '', comment: '',
  });

  async function refresh() {
    const selectedApartment = draft.apartment_id || apartments[0]?.id || '';
    const [cp, current, past] = await Promise.all([
      api<Checkpoint[]>(`/resident/checkpoints${selectedApartment ? `?apartment_id=${selectedApartment}` : ''}`, auth),
      api<Visit[]>('/visit-requests', auth),
      api<Visit[]>('/visit-requests?history=true&limit=20', auth),
    ]);
    setCheckpoints(cp);
    setActive(current);
    setHistory(past);
    setDraft((value) => ({ ...value, checkpoint_id: value.checkpoint_id || cp[0]?.id || '' }));
  }
  useEffect(() => { refresh().catch((e) => toast(e.message)); }, [auth.demoUserId, auth.authorization]);
  useEffect(() => {
    if (!draft.apartment_id) return;
    api<Checkpoint[]>(`/resident/checkpoints?apartment_id=${draft.apartment_id}`, auth)
      .then((items) => {
        setCheckpoints(items);
        setDraft((value) => ({
          ...value,
          checkpoint_id: items.some((item) => item.id === value.checkpoint_id)
            ? value.checkpoint_id
            : items[0]?.id || '',
        }));
      })
      .catch((e) => toast(e.message));
  }, [draft.apartment_id, auth.demoUserId, auth.authorization]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api<Visit>('/visit-requests', auth, json('POST', {
        apartment_id: draft.apartment_id,
        checkpoint_id: draft.checkpoint_id,
        visitor_type: draft.visitor_type,
        visitor_name: draft.visitor_name,
        visitor_car_number: draft.visitor_car_number || null,
        resident_contact: draft.resident_contact || null,
        estimated_arrival_at: draft.arrival ? new Date(draft.arrival).toISOString() : null,
        comment: draft.comment || null,
      }));
      setShowForm(false);
      setDraft((value) => ({ ...value, visitor_name: '', visitor_car_number: '', arrival: '', comment: '' }));
      toast('Заявка отправлена охране');
      await refresh();
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  }

  async function cancel(id: string) {
    try {
      await api(`/visit-requests/${id}/cancel`, auth, json('POST'));
      toast('Заявка отменена');
      await refresh();
    } catch (e) { toast((e as Error).message); }
  }

  async function linkApartment(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api('/auth/resident/register', auth, json('POST', {
        full_name: fullName,
        building: apartmentDraft.building,
        apartment: apartmentDraft.apartment,
        default_contact: contact || '',
      }));
      await onProfileChanged();
      setApartmentDraft({ building: '', apartment: '' });
      setShowApartmentForm(false);
      toast('Квартира привязана к профилю');
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  }

  const apartmentForm = showApartmentForm && <Card className="resident-inline-card"><SectionTitle title="Привязать квартиру" detail="ФИО и MAX профиль сверяются с реестром управляющей компании."/><form className="resident-apartment-form" onSubmit={linkApartment}><input aria-label="Корпус" required value={apartmentDraft.building} onChange={(e) => setApartmentDraft({ ...apartmentDraft, building: e.target.value })} placeholder="Корпус"/><input aria-label="Квартира" required value={apartmentDraft.apartment} onChange={(e) => setApartmentDraft({ ...apartmentDraft, apartment: e.target.value })} placeholder="Квартира"/><ActionButton disabled={busy}>{busy ? 'Проверяем…' : 'Добавить'}</ActionButton></form></Card>;
  const apartmentLink = <div className="apartment-link"><button className="text-action" onClick={() => setShowApartmentForm((value) => !value)}><Icon name="plus" size={15}/>{showApartmentForm ? 'Скрыть привязку квартиры' : 'Привязать ещё квартиру'}</button></div>;
  const createButton = <button className="create-cta" onClick={() => { if (showForm) setShowForm(false); else { setShowForm(true); setFormStep('type'); } }}><span className="create-cta__plus"><Icon name="plus" size={24}/></span><span><strong>{showForm ? 'Закрыть создание пропуска' : 'Создать пропуск'}</strong><small>Курьер, гость или рабочий</small></span><Icon className="create-cta__arrow" name="chevron" size={19}/></button>;
  const createFlow = showForm && <div className="resident-create-flow">
    {formStep === 'type' ? <Card className="form-card"><SectionTitle title="Кого ожидаете?" detail="Выберите тип посетителя для пропуска."/><div className="visitor-type-grid">{Object.entries(visitTypes).map(([key, label]) => <button key={key} className={draft.visitor_type === key ? 'visitor-type visitor-type--selected' : 'visitor-type'} onClick={() => { setDraft({ ...draft, visitor_type: key }); setFormStep('details'); }}><span className="visitor-type__icon"><Icon name={key === 'COURIER' ? 'pass' : key === 'GUEST' ? 'users' : key === 'REPAIR' ? 'settings' : 'profile'} size={19}/></span><strong>{label}</strong><Icon name="chevron" size={15}/></button>)}</div></Card>
      : <Card className="form-card"><div className="resident-form-heading"><button className="icon-back" onClick={() => setFormStep('type')} aria-label="Выбрать другой тип"><Icon name="chevron" size={18}/></button><SectionTitle title={`Пропуск: ${visitTypes[draft.visitor_type as keyof typeof visitTypes]}`} detail="Заполните данные, чтобы охрана увидела заявку."/></div>
        <form className="form-grid" onSubmit={submit}>
          <label>Квартира<select value={draft.apartment_id} onChange={(e) => setDraft({ ...draft, apartment_id: e.target.value })}>{apartments.map((apt) => <option key={apt.id} value={apt.id}>Корпус {apt.building} · {apt.number}</option>)}</select></label>
          <label>КПП<select required value={draft.checkpoint_id} onChange={(e) => setDraft({ ...draft, checkpoint_id: e.target.value })}>{checkpoints.map((cp) => <option key={cp.id} value={cp.id}>{cp.name}</option>)}</select></label>
          <label>ФИО посетителя<input required minLength={2} maxLength={200} value={draft.visitor_name} onChange={(e) => setDraft({ ...draft, visitor_name: e.target.value })} placeholder="Например, Алексей Петров"/></label>
          <label>Номер автомобиля <span className="muted">необязательно</span><input maxLength={24} value={draft.visitor_car_number} onChange={(e) => setDraft({ ...draft, visitor_car_number: e.target.value.toUpperCase() })} placeholder="А123АА 77"/></label>
          <label>Контакт для связи<input required minLength={3} maxLength={80} value={draft.resident_contact} onChange={(e) => setDraft({ ...draft, resident_contact: e.target.value })} placeholder="Телефон или MAX"/></label>
          <label>Ожидаемое время <span className="muted">сегодня</span><input type="datetime-local" value={draft.arrival} onChange={(e) => setDraft({ ...draft, arrival: e.target.value })}/></label>
          <label className="resident-comment-field">Комментарий <span className="muted">необязательно</span><textarea maxLength={1000} rows={3} value={draft.comment} onChange={(e) => setDraft({ ...draft, comment: e.target.value })} placeholder="Например, доставка на имя…"/></label>
          <div className="form-actions"><ActionButton type="button" tone="quiet" onClick={() => setShowForm(false)}>Отмена</ActionButton><ActionButton disabled={busy || !checkpoints.length}>{busy ? 'Отправляем…' : 'Создать пропуск'}</ActionButton></div>
        </form>
      </Card>}
  </div>;

  const activeCards = active.map((visit) => <Card key={visit.id} className="visit-card resident-visit-card">
    <div className="visit-card__top"><StatusPill status={visit.status}/><span className="muted">{new Date(visit.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span></div>
    <h3>{visit.visitor_name}</h3><p className="visit-card__sub">{visitTypes[visit.visitor_type as keyof typeof visitTypes]} · {visit.checkpoint}</p>
    <div className="metadata"><span><Icon name="building" size={13}/>Корпус {visit.building}, кв. {visit.apartment}</span>{visit.visitor_car_number && <span>Авто · {visit.visitor_car_number}</span>}</div>
    {visit.comment && <p className="comment">{visit.comment}</p>}
    <button className="text-action" onClick={() => cancel(visit.id)}>Отменить заявку</button>
  </Card>);
  const activeEmpty = <EmptyState className="empty--queue" title="Пока нет активных заявок" detail="Создайте пропуск — охрана получит уведомление и проверит данные посетителя."/>;
  const historyCards = history.length ? history.map((visit) => <Card key={visit.id} className="visit-card visit-card--compact"><div className="visit-card__top"><StatusPill status={visit.status}/><span className="muted">{new Date(visit.created_at).toLocaleDateString('ru-RU')}</span></div><h3>{visit.visitor_name}</h3><p className="visit-card__sub">{visit.checkpoint} · {visitTypes[visit.visitor_type as keyof typeof visitTypes]}</p>{visit.rejection_reason && <p className="reason">Причина: {visit.rejection_reason}</p>}</Card>) : <EmptyState title="История пока пуста" detail="Обработанные заявки сохраняются здесь до 14 дней."/>;

  return <div className="resident-screen">
    {section === 'home' && <>
      <div className="welcome-row"><div><p className="eyebrow">ДОБРЫЙ ВЕЧЕР</p><h1>{fullName.split(' ')[0]}!</h1><p className="resident-welcome-sub">{apartments[0] ? `Корпус ${apartments[0].building} · квартира ${apartments[0].number}` : 'Профиль жителя'}</p></div><div className="welcome-mark"><Icon name="home" size={23}/></div></div>
      <Card className="home-hero"><div className="hero-icon"><Icon name="building" size={21}/></div><div><p className="eyebrow">МОЙ ДОМ</p><strong>{apartments.length === 1 ? `Корпус ${apartments[0].building} · квартира ${apartments[0].number}` : `${apartments.length} квартиры`}</strong><p>Оформляйте визиты заранее — охрана увидит заявку сразу.</p></div><Icon className="home-hero__arrow" name="chevron" size={18}/></Card>
      {apartmentLink}{apartmentForm}
      <div className="section-title resident-active-heading"><div><h2>Активные пропуска</h2><p>Заявки, которые ещё действуют</p></div><button className="text-link" onClick={() => onNavigate('passes')}>Все <Icon name="chevron" size={14}/></button></div>
      <div className="stack resident-active-list">{active.length ? activeCards.slice(0, 2) : <EmptyState className="empty--queue" title="Активных пропусков пока нет" detail="Создайте заявку, чтобы охрана могла ожидать вашего гостя."/>}</div>
      <div className="resident-home-cta">{createButton}{createFlow}</div>
    </>}

    {section === 'passes' && <>
      <div className="welcome-row"><div><p className="eyebrow">ВАШИ ЗАЯВКИ</p><h1>Пропуска</h1></div><div className="welcome-mark"><Icon name="pass" size={23}/></div></div>
      {createButton}{createFlow}
      <div className="tabs" role="tablist"><button className={tab === 'active' ? 'tab tab--active' : 'tab'} onClick={() => setTab('active')}>Активные <span>{active.length}</span></button><button className={tab === 'history' ? 'tab tab--active' : 'tab'} onClick={() => setTab('history')}>История</button></div>
      <div className="stack">{tab === 'active' ? (active.length ? activeCards : activeEmpty) : historyCards}</div>
    </>}

    {section === 'profile' && <>
      <div className="welcome-row"><div><p className="eyebrow">ВАШ АККАУНТ</p><h1>Профиль</h1></div><div className="welcome-mark"><Icon name="profile" size={23}/></div></div>
      <Card className="resident-profile-card"><span className="resident-profile-avatar">{fullName.slice(0, 1)}</span><div><h2>{fullName}</h2><p>{contact || 'Контакт не указан'}</p></div></Card>
      <Card><SectionTitle title="Мои квартиры" detail="Выберите квартиру при создании пропуска."/><div className="resident-apartment-list">{apartments.map((apt) => <div className="resident-apartment-row" key={apt.id}><span className="hero-icon"><Icon name="building" size={18}/></span><span><strong>Корпус {apt.building} · квартира {apt.number}</strong><small>{apt.complex_name || 'Жилой комплекс'}</small></span><Icon name="chevron" size={16}/></div>)}</div></Card>
      {apartmentLink}{apartmentForm}
    </>}
  </div>;
}
