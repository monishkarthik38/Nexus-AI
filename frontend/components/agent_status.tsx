"use client";

import React from "react";
import { Sparkles, CheckCircle2 } from "lucide-react";

interface AgentStatusProps {
  activityLogs: string[];
  isLoading: boolean;
}

export function AgentStatus({ activityLogs, isLoading }: AgentStatusProps) {
  if (!isLoading && activityLogs.length === 0) return null;

  return (
    <div className="rounded-xl border border-indigo-900/60 bg-indigo-950/20 p-3.5 my-3">
      <div className="flex items-center space-x-2 text-xs font-semibold text-indigo-300 mb-2">
        <Sparkles className="w-3.5 h-3.5 animate-pulse text-indigo-400" />
        <span>LangGraph Research Agent Status</span>
      </div>

      <div className="space-y-1.5">
        {activityLogs.map((log, index) => {
          const isLatest = index === activityLogs.length - 1;
          return (
            <div key={index} className="flex items-center text-xs space-x-2">
              {isLatest && isLoading ? (
                <div className="w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
              )}
              <span className={isLatest && isLoading ? "text-indigo-200 font-medium" : "text-slate-400"}>
                {log}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
