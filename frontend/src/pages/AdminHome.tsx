import { FormEvent, useCallback, useEffect, useState } from 'react';
import { api, json } from '../api';
import type { AuthContext } from '../types';
import { ActionButton, Card, EmptyState, Icon, SectionTitle, StatusPill } from '../components/ui';

type Checkpoint = { id: string; name: string; active?: boolean };
type Guard = { user_id: number; full_name: string; status: string; checkpoints: Checkpoint[]; registered_at: string };
type Resident = { user_id: number; full_name: string; apartment: string; building: string; is_active: boolean; active_requests: number };
type Shift = { id: string; guard_user_id: number; guard_name: string; checkpoint_id: string; checkpoint: string; kind: string; weekday?: number | null; starts_on?: string | null; start_time?: string | null; end_time?: string | null; starts_at?: string | null; ends_at?: string | null; note?: string | null };
type VisitHistory = { id: string; visitor_name: string; status: string; apartment: string; building: string; checkpoint: string; resolved_at?: string | null; rejection_reason?: string | null };
type Audit = { id: string; actor_id?: number | null; action: string; target_id?: string | null; metadata: Record<string, unknown>; created_at?: string | null };
type AdminTab = 'summary' | 'guards' | 'checkpoints' | 'shifts' | 'residents' | 'registry' | 'history' | 'audit';
type Props = { auth: AuthContext; toast: (text: string) => void; section: string; onNavigate: (section: string) => void };
const days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
const auditActionLabels: Record<string, string> = {
  ADMIN_BOOTSTRAPPED: 'Создан первый администратор',
  CHECKPOINT_CREATED: 'Создан КПП',
  GUARD_INVITED: 'Создано приглашение охраннику',
  GUARD_APPROVED: 'Охранник подтверждён',
  GUARD_REJECTED: 'Охраннику отказано',
  GUARD_ACTIVATED: 'Доступ охранника восстановлен',
  GUARD_DEACTIVATED: 'Доступ охранника отключён',
  RESIDENT_REGISTERED: 'Зарегистрирован жилец',
  RESIDENT_APARTMENT_LINKED: 'К профилю жильца привязана квартира',
  RESIDENT_ACTIVATED: 'Доступ жильца восстановлен',
  RESIDENT_BLOCKED: 'Доступ жильца отключён',
  REGISTRY_IMPORTED: 'Импортирован реестр жильцов',
  SHIFT_CREATED: 'Создана смена',
  SHIFT_UPDATED: 'Изменена смена',
  SHIFT_DELETED: 'Удалена смена',
};
const shortDate = (value?: string | null) => value ? new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

export function AdminHome({ auth, toast, section, onNavigate }: Props) {
  const [tab, setTab] = useState<AdminTab>((section as AdminTab) || 'summary');
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [guards, setGuards] = useState<Guard[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [visitHistory, setVisitHistory] = useState<VisitHistory[]>([]);
  const [auditRows, setAuditRows] = useState<Audit[]>([]);
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<{ code: string; link?: string | null; expires_at: string } | null>(null);
  const [inviteCheckpoint, setInviteCheckpoint] = useState('');
  const [residentQuery, setResidentQuery] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [checkpointName, setCheckpointName] = useState('');
  const [editingShift, setEditingShift] = useState<string | null>(null);
  const [shiftForm, setShiftForm] = useState({
    checkpoint_id: '', guard_user_id: '', kind: 'RECURRING', weekday: '0',
    starts_on: new Date().toISOString().slice(0, 10), start_time: '08:00', end_time: '20:00',
    starts_at: '', ends_at: '', note: '',
  });

  const refresh = useCallback(async () => {
    const [cps, guardRows, shiftRows] = await Promise.all([
      api<Checkpoint[]>('/admin/checkpoints', auth),
      api<Guard[]>('/admin/guards', auth),
      api<Shift[]>('/admin/shifts', auth),
    ]);
    setCheckpoints(cps);
    setGuards(guardRows);
    setShifts(shiftRows);
    setInviteCheckpoint((value) => value || cps[0]?.id || '');
    setShiftForm((value) => ({ ...value, checkpoint_id: value.checkpoint_id || cps[0]?.id || '' }));
  }, [auth.demoUserId, auth.authorization]);

  function selectTab(next: AdminTab) {
    setTab(next);
    onNavigate(next);
  }

  useEffect(() => {
    if (['summary', 'guards', 'checkpoints', 'shifts', 'residents', 'registry', 'history', 'audit'].includes(section)) {
      setTab(section as AdminTab);
    }
  }, [section]);

  useEffect(() => { refresh().catch((e) => toast(e.message)); }, [refresh]);
  useEffect(() => {
    if (tab !== 'residents') return;
    api<Resident[]>(`/admin/residents?q=${encodeURIComponent(residentQuery)}&limit=200`, auth)
      .then(setResidents).catch((e) => toast(e.message));
  }, [tab, residentQuery, auth.demoUserId, auth.authorization]);
  useEffect(() => {
    if (tab === 'history') api<VisitHistory[]>('/admin/history?limit=200', auth).then(setVisitHistory).catch((e) => toast(e.message));
    if (tab === 'audit') api<Audit[]>('/admin/audit?limit=200', auth).then(setAuditRows).catch((e) => toast(e.message));
  }, [tab, auth.demoUserId, auth.authorization]);

  async function createInvite() {
    try {
      const result = await api<{ code: string; link?: string | null; expires_at: string }>('/admin/guard-invites', auth, json('POST', { checkpoint_id: inviteCheckpoint, expires_in_minutes: 15 }));
      setInvite(result);
      toast('Одноразовое приглашение создано');
      await refresh();
    } catch (e) { toast((e as Error).message); }
  }

  async function reviewGuard(userId: number, approve: boolean) {
    try {
      await api(`/admin/guards/${userId}/review`, auth, json('POST', { approve }));
      toast(approve ? 'Регистрация охранника подтверждена' : 'Регистрация отклонена');
      await refresh();
    } catch (e) { toast((e as Error).message); }
  }

  async function toggleResident(userId: number, active: boolean) {
    try {
      await api(`/admin/residents/${userId}/active`, auth, json('PATCH', { active }));
      setResidents((items) => items.map((item) => item.user_id === userId ? { ...item, is_active: active } : item));
      toast(active ? 'Доступ жильца восстановлен' : 'Доступ жильца отключён');
    } catch (e) { toast((e as Error).message); }
  }

  async function createCheckpoint(event: FormEvent) {
    event.preventDefault();
    try {
      await api('/admin/checkpoints', auth, json('POST', { name: checkpointName }));
      setCheckpointName('');
      await refresh();
      toast('КПП добавлен');
    } catch (e) { toast((e as Error).message); }
  }

  async function saveShift(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    const recurring = shiftForm.kind === 'RECURRING';
    const payload = recurring ? {
      checkpoint_id: shiftForm.checkpoint_id,
      guard_user_id: Number(shiftForm.guard_user_id),
      kind: shiftForm.kind,
      weekday: Number(shiftForm.weekday),
      starts_on: shiftForm.starts_on,
      start_time: shiftForm.start_time,
      end_time: shiftForm.end_time,
      note: shiftForm.note || null,
    } : {
      checkpoint_id: shiftForm.checkpoint_id,
      guard_user_id: Number(shiftForm.guard_user_id),
      kind: shiftForm.kind,
      starts_at: new Date(shiftForm.starts_at).toISOString(),
      ends_at: new Date(shiftForm.ends_at).toISOString(),
      note: shiftForm.note || null,
    };
    try {
      await api(editingShift ? `/admin/shifts/${editingShift}` : '/admin/shifts', auth, json(editingShift ? 'PATCH' : 'POST', payload));
      setEditingShift(null);
      setShiftForm((value) => ({ ...value, guard_user_id: '', starts_at: '', ends_at: '', note: '' }));
      await refresh();
      toast('Расписание смен сохранено');
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  }

  async function deleteShift(id: string) {
    try { await api(`/admin/shifts/${id}`, auth, { method: 'DELETE' }); await refresh(); toast('Смена удалена'); }
    catch (e) { toast((e as Error).message); }
  }

  async function previewImport(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    try {
      const data = await api<Record<string, unknown>>('/admin/registry/preview', auth, { method: 'POST', body: form });
      setPreview(data);
      toast('Предпросмотр реестра готов');
    } catch (e) { toast((e as Error).message); }
  }

  async function confirmImport() {
    if (!preview?.import_id) return;
    try {
      const result = await api<{ applied: number; deactivated: number }>(`/admin/registry/${preview.import_id}/confirm`, auth, json('POST', { deactivate_missing: false }));
      setPreview(null); setFile(null); await refresh();
      toast(`Импорт завершён: обработано ${result.applied} записей`);
    } catch (e) { toast((e as Error).message); }
  }

  return <>
    <div className="welcome-row"><div><p className="eyebrow">ПАНЕЛЬ УПРАВЛЕНИЯ</p><h1>{tab === 'summary' ? 'Ваш жилой комплекс' : ({ guards: 'Охрана', checkpoints: 'КПП', shifts: 'Смены', residents: 'Жильцы', registry: 'Реестр жильцов', history: 'История', audit: 'Журнал' } as Record<string, string>)[tab]}</h1></div><div className="welcome-mark welcome-mark--admin"><Icon name="settings" size={23}/></div></div>
    {tab === 'summary' && <div className="stack">
      <Card className="admin-overview-card"><span className="admin-overview-icon"><Icon name="home" size={24}/></span><div><h2>Всё для управления домом</h2><p>Выберите нужный раздел: настройте доступ охраны, расписание смен или список жильцов.</p></div></Card>
      <Card><SectionTitle title="Быстрые действия" detail="Частые задачи администратора"/><div className="quick-actions"><button onClick={() => selectTab('guards')}><span className="quick-action-icon"><Icon name="plus" size={16}/></span><strong>Создать приглашение охраннику</strong><Icon name="chevron" size={16}/></button><button onClick={() => selectTab('shifts')}><span className="quick-action-icon"><Icon name="shifts" size={16}/></span><strong>Изменить расписание смен</strong><Icon name="chevron" size={16}/></button><button onClick={() => selectTab('registry')}><span className="quick-action-icon"><Icon name="upload" size={16}/></span><strong>Загрузить реестр жильцов</strong><Icon name="chevron" size={16}/></button></div></Card>
    </div>}

    {tab === 'checkpoints' && <div className="stack"><Card><SectionTitle title="Точки доступа" detail="Настройте КПП жилого комплекса."/><div className="checkpoint-list">{checkpoints.map((cp, index) => <div className="checkpoint-row" key={cp.id}><span className="checkpoint-badge">{String(index + 1).padStart(2, '0')}</span><strong>{cp.name}</strong><span className="live-dot"/></div>)}</div><form className="inline-form" onSubmit={createCheckpoint}><input aria-label="Название КПП" value={checkpointName} onChange={(e) => setCheckpointName(e.target.value)} placeholder="Название нового КПП" required minLength={2}/><ActionButton>Добавить КПП</ActionButton></form></Card></div>}

    {tab === 'guards' && <div className="stack"><Card><SectionTitle title="Новое приглашение" detail="Одноразовая ссылка действует 15 минут и привязана к выбранному КПП."/><div className="inline-form"><select aria-label="КПП для приглашения" value={inviteCheckpoint} onChange={(e) => setInviteCheckpoint(e.target.value)}>{checkpoints.map((cp) => <option value={cp.id} key={cp.id}>{cp.name}</option>)}</select><ActionButton onClick={createInvite} disabled={!inviteCheckpoint}>Создать код</ActionButton></div>{invite && <div className="invite-result"><small>Одноразовый код · истекает {shortDate(invite.expires_at)}</small><code className="invite-result__code">{invite.code}</code>{invite.link && <a href={invite.link} target="_blank" rel="noreferrer">Открыть ссылку регистрации <Icon name="chevron" size={14}/></a>}<button onClick={() => navigator.clipboard?.writeText(invite.code).then(() => toast('Код скопирован'))}>Скопировать код</button></div>}</Card>
      <Card><SectionTitle title="Команда охраны" detail={`${guards.length} записей в реестре`}/>{guards.length ? <div className="admin-list">{guards.map((guard) => <div className="admin-list__row" key={guard.user_id}><div className="avatar avatar--guard">{guard.full_name.slice(0, 1)}</div><div className="admin-list__body"><strong>{guard.full_name}</strong><small>{guard.checkpoints.map((cp) => cp.name).join(' · ') || 'КПП не назначен'}</small></div><StatusPill status={guard.status} kind="guard"/><div className="admin-list__actions">{guard.status === 'PENDING' && <><button onClick={() => reviewGuard(guard.user_id, true)}>Подтвердить</button><button className="text-danger" onClick={() => reviewGuard(guard.user_id, false)}>Отклонить</button></>}{guard.status === 'VERIFIED' && <button className="text-danger" onClick={() => api(`/admin/guards/${guard.user_id}/active`, auth, json('PATCH', { active: false })).then(refresh).then(() => toast('Охранник отключён')).catch((e) => toast(e.message))}>Деактивировать</button>}{guard.status === 'DEACTIVATED' && <button onClick={() => api(`/admin/guards/${guard.user_id}/active`, auth, json('PATCH', { active: true })).then(refresh).then(() => toast('Доступ охранника восстановлен')).catch((e) => toast(e.message))}>Восстановить</button>}</div></div>)}</div> : <EmptyState title="Охранников пока нет" detail="Создайте одноразовое приглашение, чтобы добавить первого сотрудника."/>}</Card>
    </div>}

    {tab === 'shifts' && <div className="stack"><Card><SectionTitle title={editingShift ? 'Изменить смену' : 'Новое расписание'} detail="Поддерживаются еженедельные, разовые и замещающие смены, в том числе через полночь."/><form className="form-grid" onSubmit={saveShift}>
      <label>КПП<select required value={shiftForm.checkpoint_id} onChange={(e) => setShiftForm({ ...shiftForm, checkpoint_id: e.target.value })}>{checkpoints.map((cp) => <option key={cp.id} value={cp.id}>{cp.name}</option>)}</select></label>
      <label>Охранник<select required value={shiftForm.guard_user_id} onChange={(e) => setShiftForm({ ...shiftForm, guard_user_id: e.target.value })}><option value="">Выберите охранника</option>{guards.filter((g) => g.status === 'VERIFIED').map((guard) => <option key={guard.user_id} value={guard.user_id}>{guard.full_name}</option>)}</select></label>
      <label>Тип смены<select value={shiftForm.kind} onChange={(e) => setShiftForm({ ...shiftForm, kind: e.target.value })}><option value="RECURRING">Еженедельная</option><option value="ONE_TIME">Разовая</option><option value="REPLACEMENT">Замена</option></select></label>
      {shiftForm.kind === 'RECURRING' ? <><label>День недели<select value={shiftForm.weekday} onChange={(e) => setShiftForm({ ...shiftForm, weekday: e.target.value })}>{days.map((day, index) => <option value={index} key={day}>{day}</option>)}</select></label><label>Начало действия<input type="date" value={shiftForm.starts_on} onChange={(e) => setShiftForm({ ...shiftForm, starts_on: e.target.value })}/></label><label>Начало смены<input type="time" required value={shiftForm.start_time} onChange={(e) => setShiftForm({ ...shiftForm, start_time: e.target.value })}/></label><label>Конец смены<input type="time" required value={shiftForm.end_time} onChange={(e) => setShiftForm({ ...shiftForm, end_time: e.target.value })}/><small className="muted">Более раннее время означает переход через полночь</small></label></> : <><label>Начало<input type="datetime-local" required value={shiftForm.starts_at} onChange={(e) => setShiftForm({ ...shiftForm, starts_at: e.target.value })}/></label><label>Окончание<input type="datetime-local" required value={shiftForm.ends_at} onChange={(e) => setShiftForm({ ...shiftForm, ends_at: e.target.value })}/></label></>}
      <label>Примечание<input maxLength={300} value={shiftForm.note} onChange={(e) => setShiftForm({ ...shiftForm, note: e.target.value })} placeholder="Необязательно"/></label>
      <div className="form-actions">{editingShift && <ActionButton type="button" tone="quiet" onClick={() => setEditingShift(null)}>Отмена</ActionButton>}<ActionButton disabled={busy}>{busy ? 'Сохраняем…' : editingShift ? 'Обновить смену' : 'Добавить смену'}</ActionButton></div>
    </form></Card>
      <Card><SectionTitle title="Расписание" detail={`${shifts.length} записей · автоматическая активация по времени`}/>{shifts.length ? <div className="admin-list">{shifts.map((shift) => <div className="admin-list__row" key={shift.id}><div className="avatar avatar--shift"><Icon name="shifts" size={17}/></div><div className="admin-list__body"><strong>{shift.guard_name}</strong><small>{shift.checkpoint} · {shift.kind === 'RECURRING' ? `${days[shift.weekday ?? 0]}, ${shift.start_time?.slice(0, 5)}–${shift.end_time?.slice(0, 5)}` : `${shortDate(shift.starts_at)} — ${shortDate(shift.ends_at)}`}</small></div><div className="admin-list__actions"><button onClick={() => {
        setEditingShift(shift.id);
        setShiftForm((old) => ({ ...old, checkpoint_id: shift.checkpoint_id, guard_user_id: String(shift.guard_user_id), kind: shift.kind, weekday: String(shift.weekday ?? 0), starts_on: shift.starts_on || old.starts_on, start_time: shift.start_time?.slice(0, 5) || old.start_time, end_time: shift.end_time?.slice(0, 5) || old.end_time, starts_at: shift.starts_at ? new Date(shift.starts_at).toISOString().slice(0, 16) : '', ends_at: shift.ends_at ? new Date(shift.ends_at).toISOString().slice(0, 16) : '', note: shift.note || '' }));
      }}>Изменить</button><button className="text-danger" onClick={() => deleteShift(shift.id)}>Удалить</button></div></div>)}</div> : <EmptyState title="Смены не настроены" detail="Добавьте еженедельный график или разовую замену."/>}</Card>
    </div>}

    {tab === 'residents' && <Card><SectionTitle title="Жильцы" detail="Поиск по ФИО, корпусу или квартире. MAX ID связывается с жильцом при регистрации."/><form className="search-box" onSubmit={(e) => e.preventDefault()}><Icon name="search" size={18}/><input placeholder="Найти жильца" value={residentQuery} onChange={(e) => setResidentQuery(e.target.value)}/></form>{residents.length ? <div className="admin-list">{residents.map((resident) => <div className="admin-list__row" key={`${resident.user_id}-${resident.apartment}`}><div className="avatar">{resident.full_name.slice(0, 1)}</div><div className="admin-list__body"><strong>{resident.full_name}</strong><small>Корпус {resident.building} · квартира {resident.apartment} · MAX {resident.user_id}</small></div><span className="muted">{resident.active_requests} заявок</span><button className={resident.is_active ? 'text-danger' : ''} onClick={() => toggleResident(resident.user_id, !resident.is_active)}>{resident.is_active ? 'Отключить' : 'Восстановить'}</button></div>)}</div> : <EmptyState title="Жильцы не найдены" detail="Загрузите реестр XLSX или измените запрос."/>}</Card>}

    {tab === 'registry' && <div className="stack"><Card><SectionTitle title="Импорт реестра жильцов" detail="Обязательные столбцы: ФИО, Квартира, Корпус. Сначала проверьте предпросмотр, затем подтвердите изменения."/><form onSubmit={previewImport} className="upload-area"><label className="file-drop"><span className="file-icon"><Icon name="upload" size={18}/></span><strong>{file?.name || 'Выберите файл реестра'}</strong><small>XLSX · до 10 МБ</small><input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); }}/></label><ActionButton disabled={!file}>Проверить файл</ActionButton></form>
      {preview && <div className="preview-panel"><div className="preview-stats"><div><strong>{String(preview.new ?? 0)}</strong><small>новых</small></div><div><strong>{String(preview.updated ?? 0)}</strong><small>к обновлению</small></div><div><strong>{String(preview.would_deactivate ?? 0)}</strong><small>могут отключиться</small></div><div><strong>{String(preview.valid ?? 0)}</strong><small>корректных строк</small></div></div>{Array.isArray(preview.errors) && preview.errors.length > 0 && <div className="error-list"><strong>Ошибки строк</strong>{preview.errors.slice(0, 8).map((item, i) => <p key={i}>Строка {String((item as { row: number }).row)}: {String((item as { error: string }).error)}</p>)}{preview.errors.length > 8 && <small>Ещё {preview.errors.length - 8} ошибок</small>}</div>}<div className="safe-note">Отсутствующие в файле записи по умолчанию сохраняются. Отключение можно отдельно включить при подтверждении через API.</div><ActionButton onClick={confirmImport} disabled={Number(preview.valid) === 0}>Подтвердить импорт</ActionButton></div>}
    </Card><Card><SectionTitle title="Безопасное обновление реестра"/><p className="body-copy">Строки сначала проверяются и сохраняются как предпросмотр. Неполный или ошибочный файл не отключает существующие записи. Для синхронизации с УК используйте такой же поэтапный импорт.</p></Card></div>}

    {tab === 'history' && <Card><SectionTitle title="История проходов" detail="Заявки этого ЖК за период хранения до 14 дней."/>{visitHistory.length ? <div className="admin-list">{visitHistory.map((visit) => <div className="admin-list__row" key={visit.id}><div className="admin-list__body"><strong>{visit.visitor_name}</strong><small>{visit.checkpoint} · корпус {visit.building}, кв. {visit.apartment}{visit.resolved_at ? ` · ${shortDate(visit.resolved_at)}` : ''}</small>{visit.rejection_reason && <small className="reason">{visit.rejection_reason}</small>}</div><StatusPill status={visit.status}/></div>)}</div> : <EmptyState title="История пуста" detail="Обработанные заявки появятся здесь."/>}</Card>}

    {tab === 'audit' && <Card><SectionTitle title="Журнал действий" detail="Административные изменения и ключевые операции с заявками."/>{auditRows.length ? <div className="admin-list">{auditRows.map((event) => <div className="admin-list__row" key={event.id}><div className="avatar avatar--shift"><Icon name="history" size={17}/></div><div className="admin-list__body"><strong>{auditActionLabels[event.action] || 'Другое действие'}</strong><small>{event.created_at ? shortDate(event.created_at) : ''} · MAX ID {event.actor_id ?? 'системное событие'}{event.target_id ? ` · запись ${event.target_id.slice(0, 8)}` : ''}</small></div></div>)}</div> : <EmptyState title="Записей пока нет" detail="События появятся после изменений в панели администратора."/>}</Card>}
  </>;
}
