import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Laptop, Plug, LogOut, ShieldAlert, Settings, Boxes, KeyRound,
  FileText, KeySquare, BellRing, ShieldCheck, Scale, Radar, BarChart3,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import clsx from 'clsx';

type Item = { to: string; label: string; icon: typeof Boxes; adminOnly?: boolean };
type Group = { title: string; items: Item[] };

const GROUPS: Group[] = [
  {
    title: 'Overview',
    items: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard }],
  },
  {
    title: 'Inventory',
    items: [
      { to: '/assets', label: 'Assets', icon: Boxes },
      { to: '/devices', label: 'Devices', icon: Laptop },
      { to: '/software', label: 'Software', icon: Scale },
      { to: '/contracts', label: 'Contracts', icon: FileText },
      { to: '/entitlements', label: 'Entitlements', icon: KeySquare },
    ],
  },
  {
    title: 'Security',
    items: [
      { to: '/posture', label: 'Security Posture', icon: ShieldCheck },
      { to: '/coverage-gaps', label: 'Coverage Gaps', icon: ShieldAlert },
      { to: '/reports', label: 'Reports', icon: BarChart3 },
    ],
  },
  {
    title: 'Administration',
    items: [
      { to: '/connectors', label: 'Connectors', icon: Plug, adminOnly: true },
      { to: '/agents', label: 'Agents', icon: Radar, adminOnly: true },
      { to: '/notifications', label: 'Notifications', icon: BellRing, adminOnly: true },
      { to: '/license', label: 'License', icon: KeyRound, adminOnly: true },
      { to: '/admin', label: 'Administration', icon: Settings, adminOnly: true },
    ],
  },
];

function Sidebar() {
  const { logout, user } = useAuth();
  const isAdmin = user?.role === 'admin';

  return (
    <aside className="w-64 bg-slate-950/60 backdrop-blur-xl border-r border-slate-800 flex flex-col min-h-screen fixed">
      {/* Brand */}
      <div className="h-16 px-5 flex items-center gap-2.5 border-b border-slate-800">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 grid place-items-center shadow-glow">
          <ShieldCheck className="w-[18px] h-[18px] text-white" />
        </div>
        <div className="leading-none">
          <span className="text-[15px] font-semibold tracking-tight text-white">SyncR</span>
          <span className="block text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-0.5">Asset Intelligence</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-5">
        {GROUPS.map((group) => {
          const items = group.items.filter((i) => !i.adminOnly || isAdmin);
          if (items.length === 0) return null;
          return (
            <div key={group.title}>
              <p className="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                {group.title}
              </p>
              <div className="space-y-0.5">
                {items.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    end={link.to === '/'}
                    className={({ isActive }) =>
                      clsx(
                        'group relative flex items-center gap-3 pl-3 pr-3 py-2 rounded-lg text-sm transition-colors duration-150',
                        isActive
                          ? 'bg-indigo-500/10 text-white font-medium'
                          : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span
                          className={clsx(
                            'absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full transition-opacity',
                            isActive ? 'bg-indigo-400 opacity-100' : 'opacity-0',
                          )}
                        />
                        <link.icon className={clsx('w-[18px] h-[18px] shrink-0',
                          isActive ? 'text-indigo-400' : 'text-slate-500 group-hover:text-slate-300')} />
                        <span className="truncate">{link.label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      {/* User */}
      <div className="p-3 border-t border-slate-800">
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="w-8 h-8 rounded-lg bg-slate-800 ring-1 ring-slate-700 grid place-items-center text-sm font-semibold text-slate-200">
            {user?.username?.[0]?.toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200 truncate">{user?.username}</p>
            <p className="text-[11px] text-slate-500 capitalize truncate">{user?.role?.replace('_', ' ')}</p>
          </div>
          <button
            onClick={logout}
            className="p-2 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors"
            title="Sign out"
          >
            <LogOut className="w-[18px] h-[18px]" />
          </button>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
