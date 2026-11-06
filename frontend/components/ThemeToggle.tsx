"use client";

import { useEffect, useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("theme-change", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("theme-change", callback);
  };
}

function getTheme() {
  try { return localStorage.getItem("chat-theme") === "dark"; }
  catch { return document.documentElement.dataset.theme === "dark"; }
}

export default function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, getTheme, () => false);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  function toggle() {
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("chat-theme", dark ? "light" : "dark"); } catch { /* Storage may be disabled. */ }
    window.dispatchEvent(new Event("theme-change"));
  }

  return (
    <button type="button" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      aria-pressed={dark} title={dark ? "Switch to light mode" : "Switch to dark mode"}
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-brand-200 bg-surface text-heading hover:bg-brand-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500">
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z" />
      </svg>
    </button>
  );
}
