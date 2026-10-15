import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getSmtpSettings, saveSmtpSettings, testSmtp,
  getAlertRules, updateAlertRule, runNotifications, getNotificationLog,
} from '../api';
import type { AlertRule } from '../types';
import { BellRing, Send, Play, Mail } from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';

const RULE_LABELS: Record<string, { title: string; hint: string; noThreshold?: boolean }> = {
  contract_expiry:    { title: 'Contract renewals',   hint: 'Uses each contract\'s own notice window' },
  warranty_expiry:    { title: 'Asset warranties',    hint: 'Assets whose warranty ends within the threshold' },
  entitlement_expiry: { title: 'Software licenses',   hint: 'Entitlements expiring within the threshold' },
  license_expiry:     { title: 'Application license', hint: 'This product\'s own license file' },
  security_changes:   { title: 'Risky device changes', hint: 'New local admins, antivirus, firewall or encryption turned off — since the last email', noThreshold: true },
};

interface SmtpForm {
  host: string; port: string; username: string; password: string;
  from_address: string; use_starttls: boolean; enabled: boolean;
}

export default function Notifications() {
  const queryClient = useQueryClient();
  const [smtpForm, setSmtpForm] = useState<SmtpForm>({
    host: '', port: '25', username: '', password: '', from_address: '', use_starttls: false, enabled: true,
  });
  const [testTo, setTestTo] = useState('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [ruleDrafts, setRuleDrafts] = useState<Record<string, { days_before: string; recipients: string; enabled: boolean }>>({});

  const { data: smtpRes } = useQuery({ queryKey: ['smtp'], queryFn: getSmtpSettings });
  const { data: rulesRes } = useQuery({ queryKey: ['alert-rules'], queryFn: getAlertRules });
  const { data: logRes } = useQuery({ queryKey: ['notification-log'], queryFn: () => getNotificationLog() });

  useEffect(() => {
    const s = smtpRes?.data;
    if (s?.configured) {
      setSmtpForm({
        host: s.host ?? '', port: String(s.port ?? 25), username: s.username ?? '',
        password: '', from_address: s.from_address ?? '',
        use_starttls: !!s.use_starttls, enabled: !!s.enabled,
      });
    }
  }, [smtpRes]);

  useEffect(() => {
    const rules = rulesRes?.data;
    if (rules) {
      setRuleDrafts(Object.fromEntries(rules.map((r) => [r.rule_type, {
        days_before: String(r.days_before),
        recipients: r.recipients.join(', '),
        enabled: r.enabled,
      }])));
    }
  }, [rulesRes]);

  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detail = typeof data?.detail === 'string' ? data.detail : data?.message;
    setMessage({ ok: false, text: detail ?? 'Operation failed' });
  };

  const saveSmtp = useMutation({
    mutationFn: () => saveSmtpSettings({
      host: smtpForm.host.trim(),
      port: Number(smtpForm.port) || 25,
      username: smtpForm.username.trim() || null,
      password: smtpForm.password || null,
      from_address: smtpForm.from_address.trim(),
      use_starttls: smtpForm.use_starttls,
      enabled: smtpForm.enabled,
    }),
    onSuccess: () => {
      setMessage({ ok: true, text: 'SMTP settings saved' });
      queryClient.invalidateQueries({ queryKey: ['smtp'] });
    },
    onError,
  });

  const sendTest = useMutation({
    mutationFn: () => testSmtp(testTo.trim()),
    onSuccess: (r) => setMessage({ ok: true, text: r.message }),
    onError,
  });

  const saveRule = useMutation({
    mutationFn: (ruleType: string) => {
      const d = ruleDrafts[ruleType];
      return updateAlertRule(ruleType, {
        days_before: Number(d.days_before) || 30,
        recipients: d.recipients.split(',').map((s) => s.trim()).filter(Boolean),
        enabled: d.enabled,
      });
    },
    onSuccess: () => {
      setMessage({ ok: true, text: 'Rule saved' });
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] });
    },
    onError,
  });

  const runNow = useMutation({
    mutationFn: runNotifications,
    onSuccess: (r) => {
      const parts = Object.entries(r.data ?? {}).map(([k, v]) => `${RULE_LABELS[k]?.title ?? k}: ${v}`);
      setMessage({ ok: true, text: parts.join(' · ') });
      queryClient.invalidateQueries({ queryKey: ['notification-log'] });
    },
    onError,
  });

  const input = 'w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <BellRing className="w-8 h-8 text-indigo-400" />
            Notifications
          </h1>
          <p className="text-slate-400 mt-1">Renewal and expiry alerts via your on-prem SMTP relay. Checks run daily at 08:00 UTC.</p>
        </div>
        <button onClick={() => runNow.mutate()} disabled={runNow.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
          <Play className="w-4 h-4" /> {runNow.isPending ? 'Running…' : 'Run checks now'}
        </button>
      </div>

      {message && (
        <p className={clsx('text-sm', message.ok ? 'text-emerald-400' : 'text-rose-400')}>{message.text}</p>
      )}

      {/* SMTP settings */}
      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <h2 className="text-lg font-medium text-slate-50 mb-4 flex items-center gap-2">
          <Mail className="w-5 h-5 text-slate-400" /> SMTP relay
        </h2>
        <form onSubmit={(e) => { e.preventDefault(); saveSmtp.mutate(); }}
          className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <label className="text-sm text-slate-400">Host *
            <input required value={smtpForm.host} onChange={(e) => setSmtpForm({ ...smtpForm, host: e.target.value })}
              placeholder="mail.internal.example" className={`${input} mt-1`} />
          </label>
          <label className="text-sm text-slate-400">Port *
            <input type="number" min="1" max="65535" required value={smtpForm.port}
              onChange={(e) => setSmtpForm({ ...smtpForm, port: e.target.value })} className={`${input} mt-1`} />
          </label>
          <label className="text-sm text-slate-400">From address *
            <input required value={smtpForm.from_address}
              onChange={(e) => setSmtpForm({ ...smtpForm, from_address: e.target.value })}
              placeholder="itam@example.com" className={`${input} mt-1`} />
          </label>
          <label className="text-sm text-slate-400">Username
            <input value={smtpForm.username} onChange={(e) => setSmtpForm({ ...smtpForm, username: e.target.value })}
              placeholder="optional" className={`${input} mt-1`} />
          </label>
          <label className="text-sm text-slate-400">Password
            <input type="password" value={smtpForm.password}
              onChange={(e) => setSmtpForm({ ...smtpForm, password: e.target.value })}
              placeholder={smtpRes?.data?.has_password ? '•••••• (blank = keep)' : 'optional'}
              className={`${input} mt-1`} />
          </label>
          <div className="flex items-end gap-5 pb-1">
            <label className="flex items-center gap-2 text-sm text-slate-400">
              <input type="checkbox" checked={smtpForm.use_starttls}
                onChange={(e) => setSmtpForm({ ...smtpForm, use_starttls: e.target.checked })} className="accent-indigo-500" />
              STARTTLS
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-400">
              <input type="checkbox" checked={smtpForm.enabled}
                onChange={(e) => setSmtpForm({ ...smtpForm, enabled: e.target.checked })} className="accent-indigo-500" />
              Enabled
            </label>
          </div>
          <div className="sm:col-span-3 flex flex-col sm:flex-row gap-3 items-start sm:items-center">
            <button type="submit" disabled={saveSmtp.isPending}
              className="px-4 py-2 text-sm font-medium text-slate-50 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
              {saveSmtp.isPending ? 'Saving…' : 'Save SMTP settings'}
            </button>
            <div className="flex gap-2 sm:ml-auto">
              <input value={testTo} onChange={(e) => setTestTo(e.target.value)}
                placeholder="test recipient…" className={`${input} w-56`} />
              <button type="button" disabled={!testTo.trim() || sendTest.isPending} onClick={() => sendTest.mutate()}
                className="inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-200 bg-slate-700/60 hover:bg-slate-700 disabled:opacity-50 rounded-lg transition-colors">
                <Send className="w-4 h-4" /> Test
              </button>
            </div>
          </div>
        </form>
      </div>

      {/* Alert rules */}
      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <h2 className="text-lg font-medium text-slate-50 mb-4">Alert rules</h2>
        <div className="space-y-4">
          {(rulesRes?.data ?? []).map((r: AlertRule) => {
            const d = ruleDrafts[r.rule_type];
            if (!d) return null;
            const meta = RULE_LABELS[r.rule_type];
            return (
              <div key={r.rule_type} className="flex flex-col lg:flex-row lg:items-center gap-3 p-4 bg-slate-900/40 rounded-xl border border-slate-700/40">
                <label className="flex items-center gap-3 lg:w-64 shrink-0">
                  <input type="checkbox" checked={d.enabled}
                    onChange={(e) => setRuleDrafts({ ...ruleDrafts, [r.rule_type]: { ...d, enabled: e.target.checked } })}
                    className="accent-indigo-500" />
                  <span>
                    <span className="text-sm font-medium text-slate-200 block">{meta?.title ?? r.rule_type}</span>
                    <span className="text-xs text-slate-500">{meta?.hint}</span>
                  </span>
                </label>
                {meta?.noThreshold ? (
                  <span className="text-sm text-slate-500 lg:w-[11.5rem] shrink-0">daily digest</span>
                ) : (
                  <label className="text-sm text-slate-400 flex items-center gap-2 shrink-0">
                    within
                    <input type="number" min="1" max="365" value={d.days_before}
                      onChange={(e) => setRuleDrafts({ ...ruleDrafts, [r.rule_type]: { ...d, days_before: e.target.value } })}
                      className={`${input} w-20`} />
                    days
                  </label>
                )}
                <input value={d.recipients}
                  onChange={(e) => setRuleDrafts({ ...ruleDrafts, [r.rule_type]: { ...d, recipients: e.target.value } })}
                  placeholder="recipients, comma-separated" className={`${input} flex-1`} />
                <button onClick={() => saveRule.mutate(r.rule_type)} disabled={saveRule.isPending}
                  className="px-3 py-2 text-sm text-slate-200 bg-slate-700/60 hover:bg-slate-700 disabled:opacity-50 rounded-lg transition-colors shrink-0">
                  Save
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Log */}
      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 overflow-hidden">
        <h2 className="text-lg font-medium text-slate-50 p-6 pb-3">Recent alerts</h2>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
              <th className="px-6 py-3">When</th>
              <th className="px-6 py-3">Subject</th>
              <th className="px-6 py-3">Recipients</th>
              <th className="px-6 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {(logRes?.data ?? []).length === 0 ? (
              <tr><td colSpan={4} className="px-6 py-10 text-center text-slate-500">No alerts sent yet.</td></tr>
            ) : (logRes?.data ?? []).map((l) => (
              <tr key={l.id}>
                <td className="px-6 py-3 text-sm text-slate-400 whitespace-nowrap">{format(new Date(l.created_at), 'PP p')}</td>
                <td className="px-6 py-3 text-sm text-slate-200">{l.subject}</td>
                <td className="px-6 py-3 text-sm text-slate-400">{l.recipients.join(', ')}</td>
                <td className="px-6 py-3">
                  <span className={clsx('px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset',
                    l.status === 'sent'
                      ? 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30'
                      : 'bg-rose-500/20 text-rose-400 ring-rose-500/30')}
                    title={l.error ?? undefined}>
                    {l.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
