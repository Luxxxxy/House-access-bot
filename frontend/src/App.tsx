import { FormEvent, useEffect, useMemo, useState } from 'react';
import { MaxUI, useColorScheme } from '@maxhub/max-ui';
import '@maxhub/max-ui/dist/styles.css';
import { api, json } from './api';
import type { AuthContext, UserProfile } from './types';
import { ActionButton, Card, Icon, Notice } from './components/ui';
import { WorkspaceFrame } from './components/WorkspaceFrame';
import { ResidentHome } from './pages/ResidentHome';
import { GuardHome } from './pages/GuardHome';
import { AdminHome } from './pages/AdminHome';

type DemoUser = { user_id: number; role: string; full_name: string };
const roleLabels: Record<string, string> = {
  ADMIN: 'Администратор', GUARD: 'Охранник', RESIDENT: 'Житель', UNREGISTERED: 'Без регистрации',
};
const roleLabel = (role: string) => roleLabels[role] || 'Пользователь';
declare global {
  interface Window {
    WebApp?: {
      initData?: string;
      initDataUnsafe?: { user?: { first_name?: string; last_name?: string }; start_param?: string };
      ready?: () => void;
      expand?: () => void;
      colorScheme?: string;
    };
  }
}

function AppShell() {
  const maxColorScheme = useColorScheme();
  const [auth, setAuth] = useState<AuthContext>({});
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [demos, setDemos] = useState<DemoUser[]>([]);
  const [demoAuthEnabled, setDemoAuthEnabled] = useState(false);
  const [realMaxProfile, setRealMaxProfile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toastText, setToastText] = useState('');
  const [registrationRole, setRegistrationRole] = useState<'RESIDENT' | 'GUARD'>('RESIDENT');
  const [registration, setRegistration] = useState({ full_name: '', building: '', apartment: '', default_contact: '', invite_code: '' });
  const [busy, setBusy] = useState(false);
  const [switcher, setSwitcher] = useState(false);
  const [workspaceSection, setWorkspaceSection] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = maxColorScheme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', maxColorScheme === 'dark' ? '#101827' : '#f3f6fb');
  }, [maxColorScheme]);

  useEffect(() => { setWorkspaceSection(null); }, [auth.demoUserId, profile?.role]);

  const toast = (text: string) => {
    setToastText(text);
    window.setTimeout(() => setToastText(''), 4500);
  };
  const liveMax = Boolean(window.WebApp?.initData);
  const currentDemo = useMemo(() => demos.find((user) => user.user_id === auth.demoUserId), [demos, auth.demoUserId]);

  async function loadProfile(context: AuthContext) {
    setError('');
    const me = await api<UserProfile>('/auth/me', context);
    setProfile(me);
  }

  async function activateDemo(userId: number, authorization?: string) {
    const context: AuthContext = {
      ...(authorization ? { authorization } : {}),
      demoUserId: userId,
    };
    setRealMaxProfile(false);
    setProfile(null);
    setAuth(context);
    localStorage.setItem('demo_user_id', String(userId));
    await loadProfile(context);
  }

  useEffect(() => {
    window.WebApp?.ready?.();
    window.WebApp?.expand?.();
    const initData = window.WebApp?.initData;
    const initial: AuthContext = initData ? { authorization: `tma ${initData}` } : {};
    setAuth(initial);
    const startParam = window.WebApp?.initDataUnsafe?.start_param || '';
    if (startParam.startsWith('guard_')) {
      setRegistrationRole('GUARD');
      setRegistration((value) => ({ ...value, invite_code: startParam.slice(6) }));
    }
    async function initialize() {
      let demoEndpointAvailable = false;
      try {
        const users = await api<DemoUser[]>('/demo/users-public', {});
        demoEndpointAvailable = true;
        setDemos(users);
        setDemoAuthEnabled(true);
        if (users.length > 0) {
          const saved = Number(localStorage.getItem('demo_user_id'));
          if (saved && users.some((user) => user.user_id === saved)) {
            try { await activateDemo(saved, initial.authorization); }
            catch (e) {
              localStorage.removeItem('demo_user_id');
              setAuth(initial);
              setError((e as Error).message);
            }
          }
          return;
        }
      } catch {
        // The endpoint returns 404 outside development demo mode.
        setDemoAuthEnabled(false);
        setDemos([]);
      }

      if (initData) {
        try { await loadProfile(initial); }
        catch (e) { setError((e as Error).message); }
      } else if (!demoEndpointAvailable) {
        setError('Откройте приложение из MAX или включите локальный demo режим.');
      }
    }

    initialize().finally(() => setLoading(false));
  }, []);

  async function chooseDemo(userId: number) {
    if (!demoAuthEnabled || !demos.some((user) => user.user_id === userId)) return;
    setLoading(true);
    try { await activateDemo(userId, auth.authorization); setSwitcher(false); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }

  async function useRealMaxProfile() {
    const initData = window.WebApp?.initData;
    if (!initData) return;
    const context = { authorization: `tma ${initData}` };
    setRealMaxProfile(true);
    setAuth(context);
    setProfile(null);
    localStorage.removeItem('demo_user_id');
    setSwitcher(false);
    setLoading(true);
    try { await loadProfile(context); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }

  async function submitRegistration(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      if (registrationRole === 'RESIDENT') {
        await api('/auth/resident/register', auth, json('POST', {
          full_name: registration.full_name,
          building: registration.building,
          apartment: registration.apartment,
          default_contact: registration.default_contact,
        }));
        toast('Регистрация жильца завершена');
        await loadProfile(auth);
      } else {
        await api('/auth/guard/register', auth, json('POST', {
          invite_code: registration.invite_code,
          full_name: registration.full_name,
        }));
        toast('Заявка отправлена администратору');
        await loadProfile(auth);
      }
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  }

  function switchToDemo(userId: number) { chooseDemo(userId).catch(() => undefined); }

  if (loading) return <div className="boot-screen"><div className="brand-mark"><Icon name="shield" size={26}/></div><span>Безопасный проход</span><div className="loading-line"/></div>;
  const showDemoPicker = demoAuthEnabled && !realMaxProfile && !profile;
  if (showDemoPicker) return <div className="app app--centered">
    <header className="brand"><div className="brand-mark"><Icon name="shield" size={24}/></div><div><strong>Безопасный проход</strong><small>Цифровой пропуск в ваш дом</small></div></header>
    <Card className="auth-card"><p className="demo-mode-indicator demo-mode-indicator--picker">DEMO MODE — тестовый профиль</p><h1>Выберите профиль</h1><p className="body-copy">Выберите тестового пользователя, чтобы проверить его квартиры, заявки, КПП и права доступа.</p>{error && <p className="form-error">{error}</p>}
      {(['ADMIN', 'GUARD', 'RESIDENT'] as const).map((roleName) => {
        const users = demos.filter((user) => user.role === roleName);
        if (!users.length) return null;
        return <section className="demo-user-group" key={roleName}>
          <h2>{roleLabel(roleName)}</h2>
          <div className="demo-users">{users.map((user) => <button key={user.user_id} onClick={() => chooseDemo(user.user_id)}><span className={`avatar avatar--${user.role.toLowerCase()}`}>{user.full_name.slice(0, 1)}</span><span><strong>{user.full_name}</strong><small>{roleLabel(user.role)}</small></span><Icon name="chevron" size={16}/></button>)}</div>
        </section>;
      })}
      {demos.length === 0 && <p className="body-copy">Тестовые профили не найдены. Перезапустите backend с DEMO_SEED=true.</p>}
      {liveMax && <button className="demo-real-profile" onClick={useRealMaxProfile}>Открыть профиль моего аккаунта MAX</button>}
    </Card>
    <p className="demo-footnote">Выбор профиля доступен только при ENVIRONMENT=development и DEMO_MODE=true.</p>
  </div>;

  if (!liveMax && auth.demoUserId === undefined) return <div className="app app--centered">
    <header className="brand"><div className="brand-mark"><Icon name="shield" size={24}/></div><div><strong>Безопасный проход</strong><small>Цифровой пропуск в ваш дом</small></div></header>
    <Card className="auth-card"><h1>Откройте приложение из MAX</h1><p className="body-copy">Для входа по MAX откройте Mini App через связанного бота.</p>{error && <p className="form-error">{error}</p>}</Card>
  </div>;

  const role = profile?.role;
  const workspaceRole = role === 'ADMIN' || role === 'GUARD' || role === 'RESIDENT'
    ? role
    : null;
  const workspaceReady = profile?.is_active && (role !== 'GUARD' || profile.guard_status === 'VERIFIED');
  if (workspaceRole && workspaceReady && profile) {
    const section = workspaceSection || (role === 'ADMIN' ? 'summary' : role === 'GUARD' ? 'queue' : 'home');
    const complex = profile.apartments[0]?.complex_name || profile.admin_complexes[0]?.name || profile.guard_checkpoints[0]?.name || 'Жилой комплекс';
    return <WorkspaceFrame role={workspaceRole} name={profile.full_name || roleLabel(workspaceRole)} complex={complex} demo={Boolean(profile.demo)} realMaxProfile={realMaxProfile} demoUsers={demos} demoUserId={auth.demoUserId} liveMax={liveMax} section={section} onNavigate={setWorkspaceSection} onChooseDemo={switchToDemo} onUseRealProfile={() => { useRealMaxProfile().catch(() => undefined); }}>
      {role === 'RESIDENT' && <ResidentHome key={auth.demoUserId} auth={auth} apartments={profile.apartments} fullName={profile.full_name || 'Житель'} contact={profile.default_contact} onProfileChanged={() => loadProfile(auth)} toast={toast} section={section} onNavigate={setWorkspaceSection}/>}
      {role === 'GUARD' && <GuardHome key={auth.demoUserId} auth={auth} toast={toast} section={section} onNavigate={setWorkspaceSection} fullName={profile.full_name || 'Охранник'} complex={complex}/>}
      {role === 'ADMIN' && <AdminHome key={auth.demoUserId} auth={auth} toast={toast} section={section} onNavigate={setWorkspaceSection}/>}
    </WorkspaceFrame>;
  }
  return <div className="app">
    <header className="topbar"><div className="brand brand--compact"><div className="brand-mark"><Icon name="shield" size={22}/></div><div><strong>Безопасный проход</strong><small>{profile?.apartments[0]?.complex_name || profile?.admin_complexes[0]?.name || 'Жилой комплекс'}</small></div></div>
      {demoAuthEnabled && (profile?.demo || realMaxProfile) && <div className="profile-switch"><button onClick={() => setSwitcher((v) => !v)} aria-expanded={switcher}><span className="avatar avatar--small">{profile?.full_name?.slice(0, 1) || 'Т'}</span><span className="switch-label">{currentDemo?.full_name || profile?.full_name || 'Тестовый профиль'}</span><Icon name="chevron" size={14}/></button>{switcher && <div className="switch-menu">{demos.map((user) => <button key={user.user_id} className={auth.demoUserId === user.user_id ? 'switch-menu__active' : ''} onClick={() => switchToDemo(user.user_id)}>{user.full_name}<small>{roleLabel(user.role)}</small></button>)}{liveMax && !realMaxProfile && <button onClick={useRealMaxProfile}>Профиль моего аккаунта MAX</button>}</div>}</div>}
    </header>
    {profile?.demo && <div className="demo-mode-indicator" role="status"><strong>DEMO MODE</strong> — тестовый профиль</div>}
    {toastText && <Notice onClose={() => setToastText('')}>{toastText}</Notice>}
    <main className="page">
      {!profile && <Card className="auth-card"><h1>Подтвердите профиль</h1><p className="body-copy">Откройте приложение через связанного MAX-бота и затем зарегистрируйтесь по реестру или коду приглашения.</p></Card>}
      {profile?.role === 'UNREGISTERED' && <Card className="auth-card"><p className="eyebrow">ПЕРВЫЙ ВХОД</p><h1>Регистрация в доме</h1>{!profile.demo && <p className="body-copy">ID вашего профиля MAX: <strong>{profile.user_id}</strong></p>}<div className="tabs"><button className={registrationRole === 'RESIDENT' ? 'tab tab--active' : 'tab'} onClick={() => setRegistrationRole('RESIDENT')}>Я житель</button><button className={registrationRole === 'GUARD' ? 'tab tab--active' : 'tab'} onClick={() => setRegistrationRole('GUARD')}>Я охранник</button></div><form className="form-grid" onSubmit={submitRegistration}>
        {registrationRole === 'RESIDENT' ? <><label>ФИО как в реестре<input autoComplete="name" required minLength={5} value={registration.full_name} onChange={(e) => setRegistration({ ...registration, full_name: e.target.value })}/></label><label>Корпус<input required value={registration.building} onChange={(e) => setRegistration({ ...registration, building: e.target.value })}/></label><label>Квартира<input required value={registration.apartment} onChange={(e) => setRegistration({ ...registration, apartment: e.target.value })}/></label><label>Контакт для заявок<input required value={registration.default_contact} onChange={(e) => setRegistration({ ...registration, default_contact: e.target.value })} placeholder="Телефон или MAX"/></label></> : <><label>Одноразовый код приглашения<input required minLength={24} value={registration.invite_code} onChange={(e) => setRegistration({ ...registration, invite_code: e.target.value })}/></label><label>ФИО<input autoComplete="name" required minLength={5} value={registration.full_name} onChange={(e) => setRegistration({ ...registration, full_name: e.target.value })}/></label></>}
        <div className="form-actions"><ActionButton disabled={busy}>{busy ? 'Проверяем…' : 'Продолжить'}</ActionButton></div>
      </form></Card>}
      {role === 'GUARD' && profile?.guard_status !== 'VERIFIED' && <Card className="pending-card"><div className="pending-icon"><Icon name="shifts" size={28}/></div><h1>Профиль охранника</h1><p>{profile?.guard_status === 'REJECTED' ? 'Регистрация отклонена администратором.' : 'Регистрация ожидает подтверждения администратора. Рабочие заявки появятся после проверки.'}</p></Card>}
      {profile && !profile.is_active && <Card className="pending-card"><div className="pending-icon"><Icon name="shield" size={28}/></div><h1>Доступ приостановлен</h1><p>Обратитесь к администратору вашего жилого комплекса.</p></Card>}
    </main>
    <footer className="footer"><span>Для надёжной проверки посетителя предъявите документ охране.</span><b>Мини-приложение MAX</b></footer>
  </div>;
}

export default function App() {
  return <MaxUI><AppShell/></MaxUI>;
}
