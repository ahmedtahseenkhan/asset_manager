import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Laptop, Plug, LogOut, Shield, ShieldAlert, Settings, Boxes, KeyRound, FileText, KeySquare, BellRing } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import clsx from 'clsx';

function Sidebar() {
  const { logout, user } = useAuth();

  const links = [
    { to: '/',              label: 'Dashboard',     icon: LayoutDashboard, adminOnly: false },
    { to: '/assets',        label: 'Assets',         icon: Boxes,           adminOnly: false },
    { to: '/devices',       label: 'Devices',        icon: Laptop,          adminOnly: false },
    { to: '/contracts',     label: 'Contracts',      icon: FileText,        adminOnly: false },
    { to: '/entitlements',  label: 'Entitlements',   icon: KeySquare,       adminOnly: false },
    { to: '/coverage-gaps', label: 'Coverage Gaps',  icon: ShieldAlert,     adminOnly: false },
    { to: '/connectors',    label: 'Connectors',     icon: Plug,            adminOnly: true  },
    { to: '/notifications', label: 'Notifications',  icon: BellRing,        adminOnly: true  },
    { to: '/license',       label: 'License',        icon: KeyRound,        adminOnly: true  },
    { to: '/admin',         label: 'Administration', icon: Settings,        adminOnly: true  },
  ].filter((l) => !l.adminOnly || user?.role === 'admin');

  return (
    <div className="w-64 bg-slate-800 border-r border-slate-700 flex flex-col min-h-screen fixed">
      <div className="p-6 flex items-center gap-3">
        <Shield className="w-8 h-8 text-indigo-500" />
        <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
          SyncR
        </span>
      </div>

      <nav className="flex-1 px-4 space-y-2 mt-4">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200',
                isActive
                  ? 'bg-indigo-600/20 text-indigo-400 font-medium'
                  : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
              )
            }
          >
            {({ isActive }) => (
              <>
                <link.icon
                  className={clsx('w-5 h-5', isActive ? 'text-indigo-400' : 'text-slate-400')}
                />
                {link.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-slate-700">
        <div className="flex items-center gap-3 px-4 py-3 text-sm text-slate-400">
          <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-slate-200">
            {user?.username?.[0]?.toUpperCase()}
          </div>
          <div className="flex-1 truncate">
            <p className="font-medium text-slate-200 truncate">{user?.username}</p>
            <p className="text-xs truncate">{user?.role}</p>
          </div>
        </div>
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-4 py-3 text-slate-400 hover:text-rose-400 transition-colors rounded-xl hover:bg-rose-500/10 mt-2"
        >
          <LogOut className="w-5 h-5" />
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  );
}

export default Sidebar;
