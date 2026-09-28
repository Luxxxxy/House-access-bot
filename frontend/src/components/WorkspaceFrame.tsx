import { useState, type PropsWithChildren } from 'react';
import { Icon } from './ui';

export type WorkspaceRole = 'ADMIN' | 'GUARD' | 'RESIDENT';
export type WorkspaceDemoUser = { user_id: number; role: string; full_name: string };

type Props = PropsWithChildren<{
  role: WorkspaceRole;
  name: string;
  complex: string;
  demo: boolean;
  realMaxProfile: boolean;
  demoUsers: WorkspaceDemoUser[];
  demoUserId?: number;
  liveMax: boolean;
  section: string;
  onNavigate: (section: string) => void;
  onChooseDemo: (userId: number) => void;
  onUseRealProfile: () => void;
}>;

const roleContent = {
  RESIDENT: {
    title: 'Житель', subtitle: 'Простой и быстрый доступ для гостей, курьеров и рабочих', icon: 'home',
    links: [['home', 'Главная', 'home'], ['passes', 'Пропуска', 'pass'], ['profile', 'Профиль', 'profile']],
  },
  GUARD: {
    title: 'Охранник', subtitle: 'Обработка заявок и быстрые действия на КПП', icon: 'shield',
    links: [['queue', 'Заявки', 'shield'], ['history', 'История', 'history'], ['profile', 'Профиль', 'profile']],
  },
  ADMIN: {
    title: 'Администратор', subtitle: 'Управление жильцами, охраной, КПП и заявками', icon: 'settings',
    links: [
      ['summary', 'Обзор', 'home'], ['residents', 'Жильцы', 'users'], ['guards', 'Охрана', 'guards'],
      ['checkpoints', 'КПП', 'checkpoint'], ['shifts', 'Смены', 'shifts'], ['registry', 'Реестр пропусков', 'registry'],
      ['history', 'История', 'history'], ['audit', 'Журнал', 'book'],
    ],
  },
} satisfies Record<WorkspaceRole, { title: string; subtitle: string; icon: string; links: string[][] }>;

const roleLabel: Record<string, string> = { ADMIN: 'Администратор', GUARD: 'Охранник', RESIDENT: 'Житель' };

export function WorkspaceFrame({
  role, name, complex, demo, realMaxProfile, demoUsers, demoUserId, liveMax, section, onNavigate, onChooseDemo,
  onUseRealProfile, children,
}: Props) {
  const [switcher, setSwitcher] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const content = roleContent[role];
  const mobileLinks = role === 'ADMIN'
    ? [['summary', 'Обзор', 'home'], ['guards', 'Охрана', 'guards']]
    : content.links;
  const extraLinks = role === 'ADMIN'
    ? content.links.filter(([key]) => key !== 'summary' && key !== 'guards')
    : [];

  function navigate(key: string) {
    onNavigate(key);
    setMoreOpen(false);
  }

  return <div className={`workspace workspace--${role.toLowerCase()}`}>
    <aside className="workspace-sidebar">
      <a className="workspace-brand" href="#top" onClick={(event) => { event.preventDefault(); navigate(role === 'ADMIN' ? 'summary' : role === 'GUARD' ? 'queue' : 'home'); }}>
        <span className="workspace-brand__icon"><Icon name="shield" size={20}/></span>
        <span><strong>Безопасный проход</strong><small>{complex}</small></span>
      </a>
      <div className="workspace-sidebar__role"><span className="workspace-sidebar__role-icon"><Icon name={content.icon} size={18}/></span><span>{content.title}</span></div>
      <nav className="workspace-side-nav" aria-label="Разделы приложения">
        {content.links.map(([key, label, icon]) => <button key={key} className={section === key ? 'workspace-nav__item workspace-nav__item--active' : 'workspace-nav__item'} onClick={() => navigate(key)}>
          <Icon name={icon} size={17}/><span>{label}</span><Icon className="workspace-nav__chevron" name="chevron" size={15}/>
        </button>)}
      </nav>
      <div className="workspace-sidebar__account">
        <span className={`workspace-avatar workspace-avatar--${role.toLowerCase()}`}>{name.slice(0, 1) || 'П'}</span>
        <span className="workspace-sidebar__person"><strong>{name || content.title}</strong><small>{complex}</small></span>
        {demo && <span className="workspace-demo-dot" aria-label="Демо-профиль"/>}
      </div>
    </aside>

    <div className="workspace-main">
      <header id="top" className="workspace-masthead">
        <div className="workspace-masthead__text"><span className="workspace-masthead__icon"><Icon name={content.icon} size={24}/></span><span><strong>{content.title}</strong><small>{content.subtitle}</small></span></div>
        <div className="workspace-masthead__tools">
          {demo && <span className="demo-mode-indicator" role="status"><strong>DEMO MODE</strong> — тестовый профиль</span>}
          {(demo || realMaxProfile) && <div className="workspace-profile-switch">
            <button className="workspace-profile-switch__trigger" onClick={() => setSwitcher((value) => !value)} aria-expanded={switcher} aria-label="Сменить тестовый профиль">
              <span className="workspace-avatar workspace-avatar--small">{name.slice(0, 1) || 'П'}</span><span className="workspace-profile-switch__name">{name || 'Тестовый профиль'}</span><Icon className="workspace-profile-switch__chevron" name="chevron" size={14}/>
            </button>
            {switcher && <div className="workspace-switch-menu">{demoUsers.map((user) => <button key={user.user_id} className={user.user_id === demoUserId ? 'workspace-switch-menu__active' : ''} onClick={() => { onChooseDemo(user.user_id); setSwitcher(false); }}>{user.full_name}<small>{roleLabel[user.role] || user.role}</small></button>)}{demo && liveMax && <button className="workspace-switch-menu__real" onClick={() => { onUseRealProfile(); setSwitcher(false); }}>Профиль моего аккаунта MAX</button>}</div>}
          </div>}
        </div>
      </header>
      <main className="workspace-content">{children}</main>
      <footer className="workspace-footer"><span>Предъявите охране документ посетителя для проверки.</span><b>Мини-приложение MAX</b></footer>
      <nav className="workspace-mobile-nav" aria-label="Нижняя навигация">
        {mobileLinks.map(([key, label, icon]) => <button key={key} className={section === key ? 'workspace-mobile-nav__item workspace-mobile-nav__item--active' : 'workspace-mobile-nav__item'} onClick={() => navigate(key)}><Icon name={icon} size={19}/><span>{label}</span></button>)}
        {role === 'ADMIN' && <button className={moreOpen || extraLinks.some(([key]) => key === section) ? 'workspace-mobile-nav__item workspace-mobile-nav__item--active' : 'workspace-mobile-nav__item'} onClick={() => setMoreOpen((value) => !value)}><Icon name="menu" size={19}/><span>Ещё</span></button>}
      </nav>
      {moreOpen && role === 'ADMIN' && <div className="workspace-more-menu">{extraLinks.map(([key, label, icon]) => <button key={key} className={section === key ? 'workspace-more-menu__active' : ''} onClick={() => navigate(key)}><Icon name={icon} size={17}/>{label}</button>)}</div>}
    </div>
  </div>;
}
