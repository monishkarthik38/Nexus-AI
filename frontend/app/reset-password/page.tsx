"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { auth } from "@/lib/api";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await auth.updatePassword(password);
      setMessage("Password updated. Redirecting you to your workspace…");
      window.setTimeout(() => router.replace("/"), 900);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update your password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <section className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl shadow-black/40">
        <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-500/30 bg-indigo-500/10 text-indigo-300"><ShieldCheck className="h-6 w-6" /></div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">NEXUS AI</p>
        <h1 className="mt-2 text-2xl font-bold">Choose a new password</h1>
        <p className="mt-2 text-sm text-slate-400">Use at least 8 characters. Your reset link must be valid and unused.</p>
        <form onSubmit={submit} className="mt-7 space-y-4">
          <label className="block text-xs font-medium text-slate-300">New password
            <input type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 text-sm text-white outline-none focus:border-indigo-500" />
          </label>
          {message && <p role="status" className="rounded-xl border border-emerald-800 bg-emerald-950/30 p-3 text-xs text-emerald-300">{message}</p>}
          {error && <p role="alert" className="rounded-xl border border-rose-800 bg-rose-950/30 p-3 text-xs text-rose-300">{error}</p>}
          <button type="submit" disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Update password
          </button>
        </form>
      </section>
    </main>
  );
}
