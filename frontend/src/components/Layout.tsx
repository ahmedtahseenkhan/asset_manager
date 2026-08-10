import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import Sidebar from './Sidebar';
import { getLicenseStatus } from '../api';

function LicenseBanner() {
  const { data: res } = useQuery({
    queryKey: ['license'],
    queryFn: getLicenseStatus,
    staleTime: 5 * 60 * 1000,
  });
  const lic = res?.data;
  if (!lic || lic.status === 'valid') return null;

  const critical = !lic.operational;
  return (
    <Link
      to="/license"
      className={`mb-6 flex items-center gap-3 px-4 py-3 rounded-xl border text-sm transition-colors ${
        critical
          ? 'bg-rose-500/10 border-rose-500/30 text-rose-300 hover:bg-rose-500/20'
          : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300 hover:bg-yellow-500/20'
      }`}
    >
      <AlertTriangle className="w-4 h-4 shrink-0" />
      <span>
        {lic.reason || `License ${lic.status}`}
        {critical && ' — write operations are disabled.'}
        <span className="underline ml-1">Manage license</span>
      </span>
    </Link>
  );
}

const Layout = ({ children }: { children: React.ReactNode }) => {
  const location = useLocation();
  return (
    <div className="min-h-screen flex">
      <Sidebar />
      <main className="flex-1 ml-64 min-w-0">
        <div className="max-w-[88rem] mx-auto px-8 py-8">
          <LicenseBanner />
          <div key={location.pathname} className="page-enter">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
};

export default Layout;
