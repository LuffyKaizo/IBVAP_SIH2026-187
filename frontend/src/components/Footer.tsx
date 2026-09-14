import React from 'react';

interface FooterProps {
  coordinates?: string;
}

export const Footer: React.FC<FooterProps> = ({
  coordinates = 'DEMO BORDER SECTOR — INDIA',
}) => {
  return (
    <footer className="bg-surface border-t border-outline-variant py-3 px-6 text-[10px] text-on-surface-variant flex flex-col sm:flex-row items-center justify-between gap-2 select-none">
      <div className="flex items-center gap-1.5">
        <span className="material-symbols-outlined text-[12px] text-primary">lock</span>
        <span>CLASSIFICATION: RESTRICTED</span>
        <span className="mx-1">·</span>
        <span>{coordinates}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-success" />
        <span>ENCRYPTED · AES-256</span>
        <span className="mx-1">·</span>
        <span>{new Date().getFullYear()} IBVAP</span>
      </div>
    </footer>
  );
};
