import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { ShieldCheck, Lock, User as UserIcon } from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '../api/client';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      const res = await axios.post(`${API_BASE}/auth/login`, formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      login(res.data.access_token);
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } };
      setError(ax.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const input =
    'block w-full pl-10 pr-3 py-2.5 border border-slate-700 rounded-lg bg-white text-slate-100 ' +
    'placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all';

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-indigo-700 grid place-items-center mb-4 shadow-glow">
            <ShieldCheck className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-50">SyncR</h1>
          <p className="text-sm text-slate-400 mt-1">Sign in to your workspace</p>
        </div>

        {/* Card */}
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-7 shadow-panel">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-600 text-sm">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Username</label>
              <div className="relative">
                <UserIcon className="absolute inset-y-0 left-0 ml-3 my-auto h-4 w-4 text-slate-500" />
                <input type="text" required value={username} placeholder="admin"
                  onChange={(e) => setUsername(e.target.value)} className={input} />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Password</label>
              <div className="relative">
                <Lock className="absolute inset-y-0 left-0 ml-3 my-auto h-4 w-4 text-slate-500" />
                <input type="password" required value={password} placeholder="••••••••"
                  onChange={(e) => setPassword(e.target.value)} className={input} />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 focus:ring-offset-slate-800 transition-colors disabled:opacity-50 shadow-glow"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-500 mt-6">On-premises asset intelligence</p>
      </div>
    </div>
  );
}
