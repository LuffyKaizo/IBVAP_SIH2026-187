import React from 'react';
import { useTheme } from './ThemeProvider';

export const ThemeToggle: React.FC<{ className?: string }> = ({ className = '' }) => {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      className={`p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container-high hover:border-outline transition-all duration-200 cursor-pointer group ${className}`}
      title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
      aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
    >
      <span
        className="material-symbols-outlined text-[18px] text-on-surface-variant group-hover:text-primary transition-colors"
        style={{ fontVariationSettings: "'FILL' 1, 'wght' 300" }}
      >
        {theme === 'light' ? 'dark_mode' : 'light_mode'}
      </span>
    </button>
  );
};
