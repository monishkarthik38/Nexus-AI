import "./globals.css";
import React from "react";

export const metadata = {
  title: "NEXUS AI — Agentic Knowledge & Research Platform",
  description: "Enterprise source-grounded research assistant powered by LangGraph, Qdrant, and LLMs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
