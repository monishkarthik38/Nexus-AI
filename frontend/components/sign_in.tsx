"use client";

import React, { useState } from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { auth } from "../lib/api";

export function SignIn({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [isResettingPassword, setIsResettingPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (isResettingPassword) {
        await auth.resetPassword(email);
        setMessage("If an account exists for this email, password reset instructions have been sent.");
      } else if (isSignUp) {
        await auth.signUp(email, password);
        setMessage("Account request sent. Check your email if confirmation is enabled, then sign in.");
        setIsSignUp(false);
      } else {
        await auth.signIn(email, password);
        onAuthenticated();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <section className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl shadow-black/40">
        <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-500/30 bg-indigo-500/10 text-indigo-300">
          <ShieldCheck className="h-6 w-6" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">NEXUS AI</p>
        <h1 className="mt-2 text-2xl font-bold">{isResettingPassword ? "Reset your password" : isSignUp ? "Create your workspace access" : "Sign in to your workspace"}</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">Your documents and evidence labels are scoped to your authenticated account.</p>
        <form onSubmit={submit} className="mt-7 space-y-4">
          <label className="block text-xs font-medium text-slate-300">
            Email
            <input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 text-sm text-white outline-none focus:border-indigo-500" />
          </label>
          <label className="block text-xs font-medium text-slate-300">
            Password
            {!isResettingPassword && <input type="password" autoComplete={isSignUp ? "new-password" : "current-password"} minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 text-sm text-white outline-none focus:border-indigo-500" />}
          </label>
          {message && <p role="status" className="rounded-xl border border-slate-700 bg-slate-950/70 p-3 text-xs text-slate-300">{message}</p>}
          <button type="submit" disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
            {isResettingPassword ? "Send reset email" : isSignUp ? "Create account" : "Sign in"}
          </button>
        </form>
        <div className="mt-5 flex flex-col gap-3 text-center text-xs">
          {!isSignUp && !isResettingPassword && <button type="button" onClick={() => setIsResettingPassword(true)} className="text-slate-400 hover:text-white">Forgot password?</button>}
          <button type="button" onClick={() => { setIsSignUp((value) => !value); setIsResettingPassword(false); setMessage(null); }} className="text-slate-400 hover:text-white">
            {isSignUp || isResettingPassword ? "Back to sign in" : "Need access? Create an account"}
          </button>
        </div>
      </section>
    </main>
  );
}
